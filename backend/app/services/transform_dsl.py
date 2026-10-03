"""
The mapping formula language. It is a small XPath-flavoured expression
language — what you'd type in the Mapping Builder:

    Name/FullName                       path relative to the current for-each item
    $s1/Document/GrpHdr/MsgId           absolute path into source s1
    count(HomePhone) > 0                infix comparison, XPath function names
    concat(FName, ' ', LName)
    if(PmtMtd = 'TRF', 'TRF', 'CHK')    IF / WHEN (multi-branch) helpers
    position()

The original DSL is still accepted unchanged: {0}, {1} refer to a mapping's
ordered input chips, $name to a declared variable, UPPERCASE(...) style
function names. Text is parsed into a small AST, which can be evaluated (the
Test/Run "processor" engine), compiled to an XPath 1.0 expression (XSLT) or a
Java expression (MapStruct).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

KNOWN_FUNCS = [
    "COPY", "IDENTITY", "CONCAT", "UPPERCASE", "LOWERCASE", "TRIM", "SUBSTRING",
    "SUBSTRINGBEFORE", "SUBSTRINGAFTER", "REPLACE", "TRANSLATE",
    "CONTAINS", "STARTSWITH", "ENDSWITH", "STRINGLENGTH",
    "EQUALS", "NOTEQUALS", "GT", "LT", "GTE", "LTE", "IF", "WHEN",
    "AND", "OR", "NOT", "EXISTS", "ISEMPTY", "CURRENTDATETIME",
    "COUNT", "POSITION", "LAST", "SUM", "NUMBER", "STRING", "BOOLEAN",
    "ROUND", "FLOOR", "CEILING", "TRUE", "FALSE", "ADD", "SUB", "MUL", "DIV", "MOD",
    "CURRENTDATE", "FORMATDATETIME", "PARSEDATETIME",
    "MATCHES", "STRINGJOIN", "ABS", "MIN", "MAX", "AVG", "FORMATNUMBER", "CURRENTGROUP", "CURRENTGROUPINGKEY",
]
# Functions that only exist in XPath 2.0 (XSLT 2.0). CURRENTDATETIME/CURRENTDATE are 2.0-only when a
# time zone is given (XSLT 1.0 has EXSLT date:date-time() / date:date() in the server's zone).
XPATH2_FUNCS = {"FORMATDATETIME", "REPLACE", "MATCHES", "STRINGJOIN", "ABS", "MIN", "MAX", "AVG",
                "CURRENTGROUP", "CURRENTGROUPINGKEY"}
# Functions whose first argument is a sequence of nodes (never reduced to its first item).
_SEQ_FUNCS = {"COUNT", "SUM", "STRINGJOIN", "MIN", "MAX", "AVG"}


def needs_xpath2(node: "ExprNode") -> list[str]:
    """Function names in a formula that need XSLT 2.0."""
    out = []
    for n in walk(node):
        if n.type == "call" and (n.func in XPATH2_FUNCS or (n.func in ("CURRENTDATETIME", "CURRENTDATE") and n.args)):
            out.append(n.func_raw)
        if n.type == "ref" and n.group:
            out.append("current-group()")
    return out
JAVA_BOOL_FUNCS = {"EQUALS", "NOTEQUALS", "CONTAINS", "STARTSWITH", "ENDSWITH", "GT", "LT", "GTE", "LTE",
                   "AND", "OR", "NOT", "EXISTS", "ISEMPTY", "TRUE", "FALSE", "BOOLEAN"}

# XPath / friendly spellings -> canonical function names
FUNC_ALIASES = {
    "NORMALIZESPACE": "TRIM", "STRINGLENGTH": "STRINGLENGTH", "STARTSWITH": "STARTSWITH",
    "ENDSWITH": "ENDSWITH", "UPPER": "UPPERCASE", "LOWER": "LOWERCASE",
    "CURRENTDATETIME": "CURRENTDATETIME", "NOW": "CURRENTDATETIME", "CURRENTDATE": "CURRENTDATE",
    "FORMATDATETIME": "FORMATDATETIME", "FORMATDATE": "FORMATDATETIME", "PARSEDATETIME": "PARSEDATETIME",
    "PARSEDATE": "PARSEDATETIME", "STRINGJOIN": "STRINGJOIN", "FORMATNUMBER": "FORMATNUMBER",
    "CURRENTGROUP": "CURRENTGROUP", "CURRENTGROUPINGKEY": "CURRENTGROUPINGKEY", "AVERAGE": "AVG",
}
_OPS = {"=": "EQUALS", "!=": "NOTEQUALS", "<": "LT", "<=": "LTE", ">": "GT", ">=": "GTE",
        "and": "AND", "or": "OR", "+": "ADD", "-": "SUB", "*": "MUL", "div": "DIV", "mod": "MOD"}
_INFIX = {v: k for k, v in _OPS.items()}


@dataclass
class ExprNode:
    type: str  # 'literal' | 'placeholder' | 'var' | 'call' | 'ref'
    value: Any = None
    index: int = -1
    name: str = ""
    func: str = ""
    func_raw: str = ""
    args: list["ExprNode"] = field(default_factory=list)
    # ref: source_id ($s1/...) or None; absolute=True for $s1/... and /...; steps may hold '.' / '..'
    source_id: Optional[str] = None
    steps: list[str] = field(default_factory=list)
    absolute: bool = False
    group: bool = False  # current-group()/... — the items of the current for-each-group
    infix: bool = False
    error: Optional[str] = None


class FormulaError(ValueError):
    pass


# ------------------------------------------------------------------ lexer
_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<ph>\{\d+\})
  | (?P<op>!=|<=|>=|=|<|>|\+|\*|\(|\)|,|/|\[|\]|\|)
  | (?P<dots>\.\.|\.)
  | (?P<var>\$[A-Za-z_][\w-]*)
  | (?P<name>@?[A-Za-z_][\w\-]*(?::[A-Za-z_][\w\-]*)?)
  | (?P<minus>-)
""", re.VERBOSE)


def _lex(text: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaError(f"Unexpected character '{text[pos]}' at position {pos + 1}")
        kind = m.lastgroup
        pos = m.end()
        if kind == "ws":
            continue
        val = m.group(kind)
        if kind == "minus":
            kind, val = "op", "-"
        toks.append((kind, val))
    toks.append(("eof", ""))
    return toks


def _unquote(s: str) -> str:
    body = s[1:-1]
    # XPath strings have no escapes; only \' and \" (written by older sheet imports) are unescaped,
    # so regular expressions like \d+ survive.
    return re.sub(r"\\(['\"])", r"\1", body)


def _canon_func(raw: str) -> str:
    if ":" in raw:  # prefixed extension function (tib:..., java ...) stays custom
        return raw.upper()
    key = raw.upper().replace("-", "").replace("_", "")
    if key in FUNC_ALIASES:
        return FUNC_ALIASES[key]
    return key if key in KNOWN_FUNCS else raw.upper()


# ----------------------------------------------------------------- parser
class _Parser:
    def __init__(self, text: str):
        self.toks = _lex(text)
        self.i = 0

    def peek(self, k: int = 0) -> tuple[str, str]:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def take(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, val: str) -> None:
        kind, v = self.take()
        if v != val:
            raise FormulaError(f"Expected '{val}' but found '{v or 'end of formula'}'")

    def is_word_op(self, word: str) -> bool:
        k, v = self.peek()
        return k == "name" and v == word

    def parse(self) -> ExprNode:
        node = self.or_expr()
        if self.peek()[0] != "eof":
            raise FormulaError(f"Unexpected '{self.peek()[1]}'")
        return node

    def _bin(self, func: str, a: ExprNode, b: ExprNode) -> ExprNode:
        return ExprNode(type="call", func=func, func_raw=func, args=[a, b], infix=True)

    def or_expr(self) -> ExprNode:
        node = self.and_expr()
        while self.is_word_op("or"):
            self.take()
            node = self._bin("OR", node, self.and_expr())
        return node

    def and_expr(self) -> ExprNode:
        node = self.eq_expr()
        while self.is_word_op("and"):
            self.take()
            node = self._bin("AND", node, self.eq_expr())
        return node

    def eq_expr(self) -> ExprNode:
        node = self.rel_expr()
        while self.peek()[1] in ("=", "!=") and self.peek()[0] == "op":
            op = self.take()[1]
            node = self._bin(_OPS[op], node, self.rel_expr())
        return node

    def rel_expr(self) -> ExprNode:
        node = self.add_expr()
        while self.peek()[0] == "op" and self.peek()[1] in ("<", "<=", ">", ">="):
            op = self.take()[1]
            node = self._bin(_OPS[op], node, self.add_expr())
        return node

    def add_expr(self) -> ExprNode:
        node = self.mul_expr()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = self._bin(_OPS[op], node, self.mul_expr())
        return node

    def mul_expr(self) -> ExprNode:
        node = self.unary()
        while (self.peek()[0] == "op" and self.peek()[1] == "*") or self.is_word_op("div") or self.is_word_op("mod"):
            op = self.take()[1]
            node = self._bin(_OPS[op], node, self.unary())
        return node

    def unary(self) -> ExprNode:
        if self.peek() == ("op", "-"):
            self.take()
            inner = self.unary()
            if inner.type == "literal" and isinstance(inner.value, (int, float)):
                inner.value = -inner.value
                return inner
            return self._bin("SUB", ExprNode(type="literal", value=0), inner)
        return self.primary()

    def primary(self) -> ExprNode:
        kind, val = self.peek()
        if kind == "str":
            self.take()
            return ExprNode(type="literal", value=_unquote(val))
        if kind == "num":
            self.take()
            return ExprNode(type="literal", value=float(val) if "." in val else int(val))
        if kind == "ph":
            self.take()
            return ExprNode(type="placeholder", index=int(val[1:-1]))
        if kind == "op" and val == "(":
            self.take()
            node = self.or_expr()
            self.expect(")")
            return node
        if kind == "var":
            self.take()
            name = val[1:]
            if self.peek() == ("op", "/"):
                self.take()
                return self.path(ExprNode(type="ref", source_id=name, absolute=True))
            return ExprNode(type="var", name=name)
        if kind == "name" and self.peek(1) == ("op", "("):
            self.take()
            self.take()
            args: list[ExprNode] = []
            if self.peek() != ("op", ")"):
                args.append(self.or_expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.or_expr())
            self.expect(")")
            func = _canon_func(val)
            if func == "CURRENTGROUP" and self.peek() == ("op", "/"):
                self.take()
                return self.path(ExprNode(type="ref", group=True))
            if func == "CURRENTGROUP":
                return ExprNode(type="ref", group=True)
            return ExprNode(type="call", func=func, func_raw=val, args=args)
        if kind == "op" and val == "/":
            self.take()
            return self.path(ExprNode(type="ref", absolute=True))
        if kind in ("name", "dots"):
            return self.path(ExprNode(type="ref", absolute=False), first=True)
        raise FormulaError(f"Unexpected '{val or 'end of formula'}'")

    def path(self, ref: ExprNode, first: bool = False) -> ExprNode:
        while True:
            kind, val = self.peek()
            if kind not in ("name", "dots"):
                if first or ref.steps:
                    raise FormulaError(f"Expected a field name in path, found '{val or 'end'}'")
                break
            self.take()
            ref.steps.append(val.split(":")[-1] if kind == "name" else val)
            # numeric predicate, e.g. TitleRequest[1] — first item is what value-of uses anyway
            if self.peek() == ("op", "["):
                self.take()
                while self.peek()[1] != "]" and self.peek()[0] != "eof":
                    self.take()
                self.expect("]")
            first = False
            if self.peek() == ("op", "/"):
                self.take()
                continue
            break
        return ref


def parse_formula(text: Optional[str]) -> ExprNode:
    """Strict parse — raises FormulaError with a readable message."""
    s = (text or "").strip()
    if not s:
        return ExprNode(type="literal", value="")
    return _Parser(s).parse()


def parse_expr(text: Optional[str]) -> ExprNode:
    """Lenient parse — an unparsable formula becomes a literal carrying .error."""
    try:
        return parse_formula(text)
    except FormulaError as exc:
        return ExprNode(type="literal", value=(text or "").strip(), error=str(exc))


def walk(node: ExprNode):
    yield node
    for a in node.args:
        yield from walk(a)


def collect_refs(node: ExprNode) -> list[ExprNode]:
    return [n for n in walk(node) if n.type == "ref"]


def max_placeholder_index(node: ExprNode) -> int:
    return max((n.index for n in walk(node) if n.type == "placeholder"), default=-1)


def uses_func(node: ExprNode, func: str) -> bool:
    return any(n.type == "call" and n.func == func for n in walk(node))


def is_pure_path(node: ExprNode) -> bool:
    return node.type in ("ref", "placeholder")


# ----------------------------------------------------------------- evaluate
class EvalEnv:
    """Hooks the evaluator uses for things outside the expression itself."""

    def ref_nodes(self, node: ExprNode) -> list[Any]:  # pragma: no cover - overridden
        return []

    def node_text(self, n: Any) -> Any:  # pragma: no cover - overridden
        return n

    def position(self) -> int:
        return 1

    def last(self) -> int:
        return 1

    def grouping_key(self) -> Any:
        return None


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v != "" and v.lower() != "false"
    if isinstance(v, float) and math.isnan(v):
        return False
    return v is not None and v is not False and v != 0


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _num(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _cmp_values(a: Any, b: Any, op: str) -> bool:
    numeric = isinstance(a, (int, float)) and not isinstance(a, bool) or \
        isinstance(b, (int, float)) and not isinstance(b, bool) or op in ("<", "<=", ">", ">=")
    if numeric:
        x, y = _num(a), _num(b)
        if math.isnan(x) or math.isnan(y):
            return op == "!=" if not (math.isnan(x) and math.isnan(y)) else False
    else:
        x, y = _s(a), _s(b)
    return {"=": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]


def eval_expr(node: ExprNode, input_values: list[Any], var_values: dict[str, Any],
              env: Optional[EvalEnv] = None) -> Any:
    env = env or EvalEnv()

    def ev(n: ExprNode) -> Any:
        return eval_expr(n, input_values, var_values, env)

    def nodes_of(n: ExprNode) -> list[Any]:
        if n.type == "ref":
            return env.ref_nodes(n)
        if n.type == "placeholder":
            v = input_values[n.index] if n.index < len(input_values) else None
            return [] if v is None else [v]
        v = ev(n)
        return [] if v is None or v == "" else [v]

    if node.type == "literal":
        return node.value
    if node.type == "placeholder":
        return input_values[node.index] if node.index < len(input_values) else None
    if node.type == "var":
        return var_values.get(node.name, "")
    if node.type == "ref":
        nodes = env.ref_nodes(node)
        return env.node_text(nodes[0]) if nodes else None
    if node.type != "call":
        return None

    f = node.func
    # node-set aware functions first (they must not collapse args to a value)
    if f == "COUNT":
        return len(nodes_of(node.args[0])) if node.args else 0
    if f == "SUM":
        return sum(_num(env.node_text(x)) for x in nodes_of(node.args[0])) if node.args else 0
    if f == "EXISTS":
        return bool(node.args) and any(_s(env.node_text(x)) != "" for x in nodes_of(node.args[0]))
    if f in ("MIN", "MAX", "AVG"):
        nums = [_num(env.node_text(x)) for x in nodes_of(node.args[0])] if node.args else []
        nums = [v for v in nums if not math.isnan(v)]
        if not nums:
            return float("nan") if f == "AVG" else None
        return {"MIN": min, "MAX": max}.get(f, lambda v: sum(v) / len(v))(nums)
    if f == "STRINGJOIN":
        sep = _s(ev(node.args[1])) if len(node.args) > 1 else ""
        return sep.join(_s(env.node_text(x)) for x in nodes_of(node.args[0])) if node.args else ""
    if f == "CURRENTGROUPINGKEY":
        return env.grouping_key()
    if f == "POSITION":
        return env.position()
    if f == "LAST":
        return env.last()

    args = [ev(a) for a in node.args]
    a0 = args[0] if args else None
    if f in ("COPY", "IDENTITY", "STRING"):
        return _s(a0) if f == "STRING" else a0
    if f == "CONCAT":
        return "".join(_s(a) for a in args)
    if f == "UPPERCASE":
        return _s(a0).upper()
    if f == "LOWERCASE":
        return _s(a0).lower()
    if f == "TRIM":
        return " ".join(_s(a0).split())
    if f == "SUBSTRING":  # XPath semantics: 1-based start, optional length
        s = _s(a0)
        start = round(_num(args[1])) if len(args) > 1 else 1
        if len(args) > 2:
            end = start + round(_num(args[2]))
            return "".join(ch for i, ch in enumerate(s, start=1) if start <= i < end)
        return "".join(ch for i, ch in enumerate(s, start=1) if i >= start)
    if f == "SUBSTRINGBEFORE":
        s, t = _s(a0), _s(args[1] if len(args) > 1 else "")
        return s.split(t, 1)[0] if t and t in s else ""
    if f == "SUBSTRINGAFTER":
        s, t = _s(a0), _s(args[1] if len(args) > 1 else "")
        return s.split(t, 1)[1] if t in s else ""
    if f == "REPLACE":  # XPath 2.0 replace(): regular expression, $1 back-references
        rep = re.sub(r"\$(\d)", r"\\\1", _s(args[2] if len(args) > 2 else ""))
        try:
            return re.sub(_s(args[1] if len(args) > 1 else ""), rep, _s(a0))
        except re.error:
            return _s(a0)
    if f == "MATCHES":
        try:
            return re.search(_s(args[1] if len(args) > 1 else ""), _s(a0)) is not None
        except re.error:
            return False
    if f == "ABS":
        return abs(_num(a0))
    if f == "FORMATNUMBER":
        return _format_number(_num(a0), _s(args[1] if len(args) > 1 else "0"))
    if f == "TRANSLATE":
        src, frm, to = _s(a0), _s(args[1] if len(args) > 1 else ""), _s(args[2] if len(args) > 2 else "")
        table = {ord(c): (to[i] if i < len(to) else None) for i, c in enumerate(frm)}
        return src.translate(table)
    if f == "CONTAINS":
        return _s(args[1] if len(args) > 1 else "") in _s(a0)
    if f == "STARTSWITH":
        return _s(a0).startswith(_s(args[1] if len(args) > 1 else ""))
    if f == "ENDSWITH":
        return _s(a0).endswith(_s(args[1] if len(args) > 1 else ""))
    if f == "STRINGLENGTH":
        return len(_s(a0))
    if f in ("EQUALS", "NOTEQUALS", "GT", "LT", "GTE", "LTE"):
        op = {"EQUALS": "=", "NOTEQUALS": "!=", "GT": ">", "LT": "<", "GTE": ">=", "LTE": "<="}[f]
        return _cmp_values(a0, args[1] if len(args) > 1 else None, op)
    if f in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        x, y = _num(a0), _num(args[1] if len(args) > 1 else 0)
        try:
            return {"ADD": x + y, "SUB": x - y, "MUL": x * y,
                    "DIV": x / y if y else float("nan"), "MOD": math.fmod(x, y) if y else float("nan")}[f]
        except (OverflowError, ValueError):
            return float("nan")
    if f == "NUMBER":
        return _num(a0)
    if f == "BOOLEAN":
        return _truthy(a0)
    if f == "ROUND":
        x = _num(a0)
        return x if math.isnan(x) else math.floor(x + 0.5)
    if f == "FLOOR":
        return math.floor(_num(a0)) if not math.isnan(_num(a0)) else float("nan")
    if f == "CEILING":
        return math.ceil(_num(a0)) if not math.isnan(_num(a0)) else float("nan")
    if f == "TRUE":
        return True
    if f == "FALSE":
        return False
    if f == "AND":
        return all(_truthy(a) for a in args)
    if f == "OR":
        return any(_truthy(a) for a in args)
    if f == "NOT":
        return not _truthy(a0)
    if f == "ISEMPTY":
        return _s(a0).strip() == ""
    if f in ("CURRENTDATETIME", "CURRENTDATE"):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(_s(a0))) if a0 else datetime.now().astimezone()
        return now.replace(microsecond=0).isoformat() if f == "CURRENTDATETIME" else now.date().isoformat()
    if f in ("FORMATDATETIME", "PARSEDATETIME"):
        from app.services.datetime_fmt import py_format, py_parse
        try:
            fn = py_format if f == "FORMATDATETIME" else py_parse
            return fn(_s(a0), _s(args[1] if len(args) > 1 else ""))
        except (ValueError, KeyError):
            return ""
    if f == "IF":
        return args[1] if _truthy(a0) else (args[2] if len(args) > 2 else "")
    if f == "WHEN":
        n = len(args)
        i = 0
        while i + 1 < n - (1 if n % 2 == 1 else 0):
            if _truthy(args[i]):
                return args[i + 1]
            i += 2
        return args[-1] if n % 2 == 1 else ""
    return f"<custom {node.func_raw}(...) not evaluated in preview>"


def _format_number(v: float, picture: str) -> str:
    """format-number() for the common pictures: '0', '0.00', '#,##0.00', '000'."""
    if math.isnan(v):
        return "NaN"
    pic = picture.split(";")[0]
    decimals = len(pic.split(".")[1]) if "." in pic else 0
    min_int = len(pic.split(".")[0].replace(",", "").replace("#", ""))
    grouped = "," in pic.split(".")[0]
    out = f"{abs(v):{',' if grouped else ''}.{decimals}f}"
    int_part, _, frac = out.partition(".")
    digits = int_part.replace(",", "")
    if len(digits) < min_int:
        digits = digits.zfill(min_int)
        int_part = f"{int(digits):,}".zfill(min_int) if grouped else digits
    sign = "-" if v < 0 else ""
    return sign + int_part + (f".{frac}" if frac else "")


def eval_transform(transform: str, input_values: list[Any], var_values: Optional[dict[str, Any]] = None,
                   env: Optional[EvalEnv] = None) -> Any:
    # A blank transform means "direct copy of the first input", not "the
    # literal empty string" — parse_expr('') alone would give the latter.
    if (not transform or not transform.strip()) and input_values:
        transform = "{0}"
    return eval_expr(parse_expr(transform), input_values, var_values or {}, env)


# ----------------------------------------------------------------- to Java
def _java_cond_expr(arg_node: ExprNode, arg_java: str) -> str:
    if arg_node.type == "call" and arg_node.func in JAVA_BOOL_FUNCS:
        return arg_java
    return f"({arg_java} != null && !String.valueOf({arg_java}).isEmpty())"


def _jnum(x: str) -> str:
    return f"Double.parseDouble(String.valueOf({x}))"


def expr_to_java(node: ExprNode, args_java: list[str], custom_funcs_used: set[str],
                 jar_imports_used: set[str], jar_functions: list[dict],
                 var_inline: Optional[dict[str, str]] = None,
                 ref_java: Optional[Callable[[ExprNode], str]] = None) -> str:
    var_inline = var_inline or {}

    def j(n: ExprNode) -> str:
        return expr_to_java(n, args_java, custom_funcs_used, jar_imports_used, jar_functions, var_inline, ref_java)

    if node.type == "literal":
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, (int, float)):
            return str(node.value)
        escaped = str(node.value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if node.type == "placeholder":
        return args_java[node.index] if node.index < len(args_java) else "null"
    if node.type == "var":
        return var_inline.get(node.name, re.sub(r"[^A-Za-z0-9_]", "_", node.name) or "_")
    if node.type == "ref":
        return ref_java(node) if ref_java else "null"
    if node.type != "call":
        return "null"
    a = [j(x) for x in node.args]
    a0 = a[0] if a else "null"
    f = node.func
    if f in ("COPY", "IDENTITY"):
        return a0
    if f == "STRING":
        return f"String.valueOf({a0})"
    if f == "CONCAT":
        return " + ".join(f"String.valueOf({x})" for x in a) or '""'
    if f == "UPPERCASE":
        return f"String.valueOf({a0}).toUpperCase()"
    if f == "LOWERCASE":
        return f"String.valueOf({a0}).toLowerCase()"
    if f == "TRIM":
        return f"String.valueOf({a0}).trim().replaceAll(\"\\\\s+\", \" \")"
    if f == "SUBSTRING":
        start = f"(int) Math.round({_jnum(a[1])}) - 1" if len(a) > 1 else "0"
        if len(a) > 2:
            return (f"String.valueOf({a0}).substring(Math.max(0, {start}), "
                    f"Math.min(String.valueOf({a0}).length(), Math.max(0, {start} + (int) Math.round({_jnum(a[2])}))))")
        return f"String.valueOf({a0}).substring(Math.max(0, {start}))"
    if f == "SUBSTRINGBEFORE":
        return f"org.apache.commons.lang3.StringUtils.substringBefore(String.valueOf({a0}), {a[1]})"
    if f == "SUBSTRINGAFTER":
        return f"org.apache.commons.lang3.StringUtils.substringAfter(String.valueOf({a0}), {a[1]})"
    if f == "REPLACE":
        return f"String.valueOf({a0}).replace({a[1]}, {a[2]})"
    if f == "CONTAINS":
        return f"String.valueOf({a0}).contains({a[1]})"
    if f == "STARTSWITH":
        return f"String.valueOf({a0}).startsWith({a[1]})"
    if f == "ENDSWITH":
        return f"String.valueOf({a0}).endsWith({a[1]})"
    if f == "STRINGLENGTH":
        return f"String.valueOf({a0}).length()"
    if f == "EQUALS":
        return f"(String.valueOf({a0}).equals(String.valueOf({a[1]})))"
    if f == "NOTEQUALS":
        return f"(!String.valueOf({a0}).equals(String.valueOf({a[1]})))"
    if f in ("GT", "LT", "GTE", "LTE"):
        op = {"GT": ">", "LT": "<", "GTE": ">=", "LTE": "<="}[f]
        return f"({_jnum(a0)} {op} {_jnum(a[1])})"
    if f in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        op = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%"}[f]
        return f"({_jnum(a0)} {op} {_jnum(a[1])})"
    if f == "NUMBER":
        return _jnum(a0)
    if f in ("ROUND", "FLOOR", "CEILING"):
        return f"Math.{ {'ROUND': 'round', 'FLOOR': 'floor', 'CEILING': 'ceil'}[f] }({_jnum(a0)})"
    if f == "TRUE":
        return "true"
    if f == "FALSE":
        return "false"
    if f == "BOOLEAN":
        return _java_cond_expr(node.args[0], a0)
    if f == "COUNT":
        return f"({a0} == null ? 0 : ({a0} instanceof java.util.Collection<?> c ? c.size() : 1))"
    if f in ("POSITION", "LAST", "SUM", "TRANSLATE"):
        return f"null /* TODO {node.func_raw}() has no MapStruct equivalent */"
    if f == "AND":
        return "(" + " && ".join(_java_cond_expr(n, x) for n, x in zip(node.args, a)) + ")"
    if f == "OR":
        return "(" + " || ".join(_java_cond_expr(n, x) for n, x in zip(node.args, a)) + ")"
    if f == "NOT":
        return f"!{_java_cond_expr(node.args[0], a0)}"
    if f == "EXISTS":
        return f"({a0} != null && !String.valueOf({a0}).isEmpty())"
    if f == "ISEMPTY":
        return f"({a0} == null || String.valueOf({a0}).isBlank())"
    if f in ("CURRENTDATETIME", "CURRENTDATE"):
        zone = f"java.time.ZoneId.of({a0})" if a else "java.time.ZoneId.systemDefault()"
        if f == "CURRENTDATE":
            return f"java.time.LocalDate.now({zone}).toString()"
        return (f"java.time.ZonedDateTime.now({zone}).withNano(0)"
                f".format(java.time.format.DateTimeFormatter.ISO_OFFSET_DATE_TIME)")
    if f in ("FORMATDATETIME", "PARSEDATETIME"):
        from app.services.datetime_fmt import has_time, to_java, tokenize
        pat_node = node.args[1] if len(node.args) > 1 else None
        if pat_node is None or pat_node.type != "literal":
            return f"null /* TODO {node.func_raw}() needs a literal pattern */"
        toks = tokenize(str(pat_node.value))
        fmt = f'java.time.format.DateTimeFormatter.ofPattern("{to_java(toks)}")'
        s0 = f"String.valueOf({a0})"
        if f == "FORMATDATETIME":
            return (f"{fmt}.format(java.time.LocalDateTime.parse({s0}.length() <= 10 ? {s0} + \"T00:00:00\" "
                    f": {s0}.substring(0, 19)))")
        cls = "java.time.LocalDateTime" if has_time(toks) else "java.time.LocalDate"
        return f"{cls}.parse({s0}, {fmt}).toString()"
    if f == "IF":
        return f"({_java_cond_expr(node.args[0], a0)} ? {a[1]} : {a[2] if len(a) > 2 else 'null'})"
    if f == "WHEN":
        expr = a[-1] if len(a) % 2 == 1 else "null"
        i = len(a) - (3 if len(a) % 2 == 1 else 2)
        while i >= 0:
            expr = f"({_java_cond_expr(node.args[i], a[i])} ? {a[i + 1]} : {expr})"
            i -= 2
        return expr
    jf = next((x for x in jar_functions if x["method_name"].upper() == f), None)
    if jf:
        jar_imports_used.add(jf["class_name"])
        return f"{jf['class_name'].split('.')[-1]}.{jf['method_name']}({', '.join(a)})"
    raw_name = re.sub(r"[^A-Za-z0-9_]", "_", node.func_raw or f.lower())
    custom_funcs_used.add(raw_name)
    return f"CustomFunctions.{raw_name}({', '.join(a)})"


# ----------------------------------------------------------------- to XPath
_XPATH_FUNC = {
    "CONCAT": "concat", "SUBSTRING": "substring", "SUBSTRINGBEFORE": "substring-before",
    "SUBSTRINGAFTER": "substring-after", "TRANSLATE": "translate", "CONTAINS": "contains",
    "STARTSWITH": "starts-with", "STRINGLENGTH": "string-length", "TRIM": "normalize-space",
    "COUNT": "count", "POSITION": "position", "LAST": "last", "SUM": "sum", "NUMBER": "number",
    "STRING": "string", "BOOLEAN": "boolean", "ROUND": "round", "FLOOR": "floor",
    "CEILING": "ceiling", "TRUE": "true", "FALSE": "false", "NOT": "not",
}


def _xp_literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true()" if v else "false()"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in s.split("'")) + ")"


def expr_to_xpath(node: ExprNode, args_xpath: list[str],
                  ref_xpath: Optional[Callable[[ExprNode], str]] = None,
                  version: str = "2.0", single: bool = False) -> Any:
    """Returns an XPath string for the given XSLT version, or a dict marker {'cond': node} for
    IF/WHEN, which the XSLT generator turns into an xsl:choose block.

    In XSLT 2.0 a path that matches several nodes is a sequence, and string functions reject
    sequences — so wherever a single value is expected (single=True), paths become (path)[1],
    which is also what XSLT 1.0 and the processor engine do implicitly."""
    v2 = version.startswith("2")

    def x(n: ExprNode, one: bool = True) -> Any:
        return expr_to_xpath(n, args_xpath, ref_xpath, version, one)

    def one(xp: str) -> str:
        return f"({xp})[1]" if v2 and single else xp

    if node.type == "literal":
        return _xp_literal(node.value)
    if node.type == "placeholder":
        return one(args_xpath[node.index]) if node.index < len(args_xpath) else "''"
    if node.type == "var":
        return f"${node.name}"
    if node.type == "ref":
        if node.group:
            if not v2:
                return "/.."  # no grouping in XSLT 1.0 (reported as a problem): an empty node-set
            xp = ref_xpath(node) if ref_xpath else "current-group()" + ("/" + "/".join(node.steps) if node.steps else "")
            return one(xp) if node.steps else xp
        xp = ref_xpath(node) if ref_xpath else ("/" if node.absolute else "") + "/".join(node.steps)
        return one(xp)
    if node.type != "call":
        return "''"
    if node.func in ("IF", "WHEN"):
        return {"cond": node}
    f = node.func
    a = [x(n, not (f in _SEQ_FUNCS and i == 0)) for i, n in enumerate(node.args)]
    if any(isinstance(v, dict) for v in a):
        return "'/* unsupported: IF/WHEN nested inside another function */'"
    a0 = a[0] if a else "''"
    if f in ("COPY", "IDENTITY"):
        return a0
    if f in _XPATH_FUNC:
        return f"{_XPATH_FUNC[f]}({', '.join(a)})"
    if f in _INFIX:
        return f"({a0} {_INFIX[f]} {a[1] if len(a) > 1 else ''})"
    if f == "AND":
        return "(" + " and ".join(a) + ")"
    if f == "OR":
        return "(" + " or ".join(a) + ")"
    if f == "EXISTS":
        return f"(string-length(normalize-space({a0})) > 0)"
    if f == "ISEMPTY":
        return f"(string-length(normalize-space({a0})) = 0)"
    if f == "FORMATNUMBER":
        return f"format-number({a0}, {a[1] if len(a) > 1 else _xp_literal('0')})"
    if f == "PARSEDATETIME":  # substring() extraction: works in both versions
        from app.services.datetime_fmt import xpath_parse
        pat_node = node.args[1] if len(node.args) > 1 else None
        out = xpath_parse(f"normalize-space({a0})", str(pat_node.value)) if pat_node is not None and pat_node.type == "literal" else None
        return out or "'/* parse-dateTime needs a fixed-width literal pattern, e.g. dd/MM/yyyy */'"

    if not v2:
        # ---------------- XSLT 1.0
        if f == "UPPERCASE":
            return f"translate({a0}, 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')"
        if f == "LOWERCASE":
            return f"translate({a0}, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
        if f == "ENDSWITH":
            return f"(substring({a0}, string-length({a0}) - string-length({a[1]}) + 1) = {a[1]})"
        if f in ("CURRENTDATETIME", "CURRENTDATE"):
            # EXSLT, in the server's zone (a requested zone needs XSLT 2.0 — reported as a problem)
            return "date:date-time()" if f == "CURRENTDATETIME" else "date:date()"
        if ":" in node.func_raw:
            return f"{node.func_raw}({', '.join(a)})"
        # 2.0-only functions (reported as problems) degrade to the nearest usable 1.0 value
        if f == "MATCHES":
            return "false()"
        if f == "CURRENTGROUPINGKEY":
            return "''"
        if f in ("MIN", "MAX", "AVG", "STRINGJOIN"):
            return f"string(({a0})[1])" if a else "''"
        return a0  # replace / abs / format-dateTime: the input value unchanged

    # -------------------- XSLT 2.0
    if f in ("UPPERCASE", "LOWERCASE", "ENDSWITH", "REPLACE", "MATCHES", "ABS", "MIN", "MAX", "AVG"):
        name = {"UPPERCASE": "upper-case", "LOWERCASE": "lower-case", "ENDSWITH": "ends-with"}.get(f, f.lower())
        return f"{name}({', '.join(a)})"
    if f == "STRINGJOIN":
        return f"string-join({a0}, {a[1] if len(a) > 1 else _xp_literal('')})"
    if f == "CURRENTGROUPINGKEY":
        return "current-grouping-key()"
    if f in ("CURRENTDATETIME", "CURRENTDATE"):
        # The zone's offset is fixed when the XSLT is generated.
        from app.services.datetime_fmt import zone_offset
        tz = node.args[0].value if node.args and node.args[0].type == "literal" else None
        try:
            off = zone_offset(str(tz)) if tz else None
        except Exception:  # noqa: BLE001 - unknown zone name
            off = None
        now = f"adjust-dateTime-to-timezone(current-dateTime(), xs:dayTimeDuration('{off}'))" if off else "current-dateTime()"
        pic = "[Y0001]-[M01]-[D01]" if f == "CURRENTDATE" else "[Y0001]-[M01]-[D01]T[H01]:[m01]:[s01][Z]"
        return f"format-dateTime({now}, '{pic}')"
    if f == "FORMATDATETIME":
        from app.services.datetime_fmt import to_picture, tokenize
        pat_node = node.args[1] if len(node.args) > 1 else None
        literal = pat_node is not None and pat_node.type == "literal"
        v = f"normalize-space({a0})"
        pic = _xp_literal(to_picture(tokenize(str(pat_node.value)))) if literal else (a[1] if len(a) > 1 else "''")
        dt = f"xs:dateTime(if (string-length({v}) <= 10) then concat({v}, 'T00:00:00') else {v})"
        return f"(if ({v} = '') then '' else format-dateTime({dt}, {pic}))"
    if ":" in node.func_raw:  # prefixed extension function: pass through as written
        return f"{node.func_raw}({', '.join(a)})"
    return a0


def check_formula(text: str) -> Optional[str]:
    """None if the formula parses, else a readable error."""
    try:
        parse_formula(text)
        return None
    except FormulaError as exc:
        return str(exc)

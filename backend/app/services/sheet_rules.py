"""
Mapping-sheet rules -> formulas.

Each sheet row gives a target path, optionally a source path, and a rule written by a person, e.g.

    If PmtInf/PmtMtd = ‘TRF’. Then map ‘TRF’ else map ‘HIGH’
    Hardcode to NORM          Default value: SEPA          Copy from MsgId
    Direct                    IF(PmtMtd = 'TRF', 'TRF', 'HIGH')

1. The rule is understood locally where possible: curly quotes, if / then / else (also nested
   "else if"), is / equals / is not / is empty / is present / in (...), and / or, constants, copy-from,
   direct mapping, and rules that are already formulas. Field names are looked up in the source tree
   (full path, partial path or a unique field name).
2. Field references are written relative to the target's for-each item. A repeating target parent
   (PmtInf[]) gets a For-Each over the matching repeating source element (PmtInf) when the rule reads
   from inside it, so every payment is mapped, not just the first.
3. Every formula is checked (it must parse, and its source paths must exist). What can't be understood
   or doesn't pass is sent to the LLM in one request, with the target's loop context and the relevant
   source fields. Its answers are checked the same way; failures are retried once with the errors.
4. Every row gets a report line: how it was mapped (rule / AI / review) and why.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from app.models.schemas import (
    FieldNode, MappingRule, MappingWorkspace, SheetImportRow, SheetRowReport, Statement, TargetStructure,
)
from app.services.links import analyse
from app.services.llm_client import LlmError, call_llm, extract_json
from app.services.mapping_logic import ensure_target_path, norm_key
from app.services.parsers import flatten
from app.services.structure import LOOP_KINDS, LoopCtx, Structure, segments
from app.services.transform_dsl import check_formula

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'", "´": "'",
                         "“": '"', "”": '"', "„": '"', "″": '"'})
_KEYWORDS = {"and", "or", "not", "div", "mod", "true", "false", "if", "then", "else", "null"}
_VERBS = r"(?:(?:map|set|use|populate|send|return|default|value|output|give|put|hard\s*code(?:d)?|be)\s+)*(?:(?:it|to|as|with|the|value|of)\s+)*"
_MARK = "\x00"


# ------------------------------------------------------------------ source field lookup
class Fields:
    """All source nodes, for resolving the names people write in sheets."""

    def __init__(self, ws: MappingWorkspace, hint: Optional[str] = None):
        sources = ws.sources
        if hint:
            chosen = [s for s in sources if hint.strip() in (s.id, s.label)]
            sources = chosen or sources
        self.first = ws.sources[0].id if ws.sources else "s1"
        self.nodes: list[tuple[str, FieldNode]] = [(s.id, n) for s in sources for n in flatten(s.fields)]
        self.by_key = [(sid, n, norm_key(n.path)) for sid, n in self.nodes]
        self.ambiguous: list[str] = []

    def resolve(self, raw: str) -> Optional[tuple[str, FieldNode]]:
        text = raw.strip().strip("'\"")
        sid = None
        m = re.match(r"^\$(\w+)/(.*)$", text)
        if m:
            sid, text = m.group(1), m.group(2)
        key = norm_key(text)
        if not key:
            return None
        pool = [x for x in self.by_key if sid is None or x[0] == sid]
        for cond in (lambda k: k == key, lambda k: k.endswith("." + key)):
            hits = [(s, n) for s, n, k in pool if cond(k)]
            if hits:
                if len({(s, n.path) for s, n in hits}) > 1:
                    self.ambiguous.append(f"'{raw.strip()}' matches {len(hits)} source fields "
                                          f"({', '.join('/'.join(segments(n.path)) for _s, n in hits[:3])}"
                                          f"{', …' if len(hits) > 3 else ''})")
                return hits[0]
        last = key.split(".")[-1]
        hits = [(s, n) for s, n, k in pool if k.split(".")[-1] == last]
        if len(hits) > 1:
            self.ambiguous.append(f"'{raw.strip()}' matches {len(hits)} source fields named {last}")
        return hits[0] if len(hits) == 1 else None


def _abs_segments(n: FieldNode) -> list[str]:
    return segments(n.path)


def ref_for(sid: str, segs: list[str], ctx: list[LoopCtx], first: str) -> str:
    """Formula text for a source field, relative to the innermost loop that contains it."""
    for loop in reversed(ctx):
        lsegs = segments(loop.path)
        if loop.source_id == sid and segs[:len(lsegs)] == lsegs and len(segs) > len(lsegs):
            return "/".join(segs[len(lsegs):])
    if not ctx and sid == first:
        return "/".join(segs)
    return f"${sid}/" + "/".join(segs)


# ------------------------------------------------------------------ rule text -> formula skeleton
def _split_quoted(text: str) -> list[tuple[bool, str]]:
    parts = re.split(r"('(?:[^'\\]|\\.)*'|\"[^\"]*\")", text)
    return [(i % 2 == 1, p) for i, p in enumerate(parts) if p]


def _lit(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return "'" + v.replace("'", "\\'") + "'"


class RuleCompiler:
    """Turns one rule into a formula whose field references are marked, so they can be rendered
    relative to the loop context once it is known."""

    def __init__(self, fields: Fields):
        self.f = fields
        self.refs: list[tuple[str, FieldNode]] = []
        self.unclear: list[str] = []

    def mark(self, sid: str, node: FieldNode) -> str:
        self.refs.append((sid, node))
        return f"{_MARK}{sid}|{node.path}{_MARK}"

    def path_or_none(self, text: str) -> Optional[str]:
        t = text.strip()
        if not t or not re.fullmatch(r"\$?[\w@][\w@./\[\]$-]*", t):
            return None
        hit = self.f.resolve(t)
        return self.mark(*hit) if hit else None

    def value(self, text: str) -> str:
        """A then / else / constant operand: literal, number, field, or (nested) rule."""
        t = re.sub(rf"^{_VERBS}", "", text.strip(), flags=re.I).strip().rstrip(".;,").strip()
        if re.match(r"(?i)^if\b", t):
            return self.rule(t) or _lit(t)
        if re.fullmatch(r"'(?:[^'\\]|\\.)*'|\"[^\"]*\"", t):
            return _lit(t)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
            return t
        if re.fullmatch(r"(?i)blank|empty|nothing|null|space|''", t):
            return "''"
        p = self.path_or_none(t)
        if p:
            return p
        f = self.formula(t)
        if f is not None and re.search(r"[(/$]", t):
            return f
        if re.search(r"\s", t) or re.search(r"[a-z]", t):
            self.unclear.append(f"'{t}' was read as fixed text (not quoted, not a source field)")
        return _lit(t)

    def condition(self, text: str) -> Optional[str]:
        t = text.strip().rstrip(".,;:").strip()
        t = re.sub(r"(?i)^\((.*)\)$", r"\1", t)
        # and / or outside quotes
        parts, ops, buf = [], [], ""
        for quoted, chunk in _split_quoted(t):
            if quoted:
                buf += chunk
                continue
            pieces = re.split(r"(?i)\s+(and|or)\s+", chunk)
            buf += pieces[0]
            for i in range(1, len(pieces), 2):
                parts.append(buf)
                ops.append(pieces[i].lower())
                buf = pieces[i + 1]
        parts.append(buf)
        atoms = [self.atom(p) for p in parts]
        if any(a is None for a in atoms):
            return None
        out = atoms[0]
        for op, a in zip(ops, atoms[1:]):
            out = f"{out} {op} {a}"
        return out

    def atom(self, text: str) -> Optional[str]:
        t = text.strip()
        m = re.fullmatch(r"(?i)(?P<l>.+?)\s+(?:is\s+)?(?:empty|blank|null|missing|not\s+(?:present|provided|populated|available|given))", t)
        if m:
            left = self.operand(m.group("l"))
            return f"{left} = ''" if left else None
        m = re.fullmatch(r"(?i)(?P<l>.+?)\s+(?:is\s+)?(?:not\s+(?:empty|blank|null)|present|provided|populated|available|exists|given)", t)
        if m:
            left = self.operand(m.group("l"))
            return f"{left} != ''" if left else None
        m = re.fullmatch(r"(?i)(?P<l>.+?)\s+(?P<neg>not\s+)?in\s*\((?P<r>.+)\)", t)
        if m:
            left = self.operand(m.group("l"))
            vals = [self.value(v) for v in re.split(r"\s*,\s*", m.group("r")) if v.strip()]
            if not left or not vals:
                return None
            op, join = ("!=", " and ") if m.group("neg") else ("=", " or ")
            return "(" + join.join(f"{left} {op} {v}" for v in vals) + ")"
        m = re.fullmatch(r"(?i)(?P<l>.+?)\s*(?P<op>==|!=|<>|<=|>=|=|<|>|\bis\s+not\b|\bnot\s+equals?(?:\s+to)?\b|"
                         r"\bdoes\s+not\s+equal\b|\bequals?(?:\s+to)?\b|\bis\b|\bgreater\s+than\b|\bless\s+than\b)\s*(?P<r>.+)", t)
        if m:
            op = re.sub(r"\s+", " ", m.group("op").lower())
            op = {"==": "=", "<>": "!=", "is not": "!=", "is": "=", "greater than": ">", "less than": "<",
                  "does not equal": "!="}.get(op, op)
            if op.startswith("not equal"):
                op = "!="
            elif op.startswith("equal"):
                op = "="
            left, right = self.operand(m.group("l")), self.value(m.group("r"))
            return f"{left} {op} {right}" if left else None
        return self.formula(t)

    def operand(self, text: str) -> Optional[str]:
        t = re.sub(r"(?i)^(?:the\s+)?(?:value\s+of\s+)?", "", text.strip())
        return self.path_or_none(t) or self.formula(t)

    def formula(self, text: str) -> Optional[str]:
        """Text that already is a formula: field names marked, double quotes made single."""
        out = ""
        for quoted, chunk in _split_quoted(text):
            if quoted:
                out += _lit(chunk)
                continue

            def repl(m: re.Match) -> str:
                tok = m.group(0)
                if tok.lower() in _KEYWORDS or tok.startswith("$") and "/" not in tok:
                    return tok
                if re.fullmatch(r"\d+(\.\d+)?", tok):
                    return tok
                hit = self.f.resolve(tok)
                return self.mark(*hit) if hit else tok

            out += re.sub(r"(?<![\w@$/.\-])\$?[A-Za-z_@][\w@.\-]*(?:/[\w@.\[\]\-]+)*(?![\w(])(?!\s*\()", repl, chunk)
        if check_formula(re.sub(f"{_MARK}[^{_MARK}]*{_MARK}", "x", out)):
            return None  # prose, not a formula
        return out

    def rule(self, text: str) -> Optional[str]:
        t = re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().rstrip(".;").strip()
        if not t:
            return None
        m = re.fullmatch(r"(?i)if\s+(?P<c>.+?)\s*[,.;:]?\s*then\s*[,:]?\s+(?P<t>.+?)"
                         r"(?:\s*[,.;]?\s*(?:else|otherwise)\s*[,:]?\s+(?P<e>.+))?", t) \
            or re.fullmatch(r"(?i)if\s+(?P<c>.+?)\s*,\s*(?P<t>.+?)(?:\s*[,.;]?\s*(?:else|otherwise)\s*[,:]?\s+(?P<e>.+))?", t)
        if m:
            cond = self.condition(m.group("c"))
            if cond is None:
                return None
            then = self.value(m.group("t"))
            other = self.value(m.group("e")) if m.group("e") else "''"
            return f"if({cond}, {then}, {other})"
        m = re.fullmatch(r"(?i)(?:hard[- ]?code(?:d)?|constant|fixed|static|always|default)(?:\s+(?:value|as|to|with|of))*\s*[:=]?\s*(?P<v>.+)", t) \
            or re.fullmatch(r"(?i)(?:set|populate|map)\s+(?:it\s+)?(?:to|as|with)\s+(?:constant\s+|value\s+)?(?P<v>'[^']*'|\"[^\"]*\"|[A-Z0-9_\-]+)", t)
        if m:
            return _lit(m.group("v")) if not re.fullmatch(r"-?\d+(\.\d+)?", m.group("v").strip()) else m.group("v").strip()
        m = re.fullmatch(r"(?i)(?:copy|map|move|take|populate|derive|get|use|read)\s+(?:the\s+)?(?:value\s+)?(?:from|of)\s+(?:the\s+)?(?:field\s+)?(?P<p>.+)", t)
        if m:
            return self.path_or_none(m.group("p")) or self.formula(m.group("p"))
        if re.fullmatch(r"'(?:[^'\\]|\\.)*'|\"[^\"]*\"", t):
            return _lit(t)
        return self.path_or_none(t) or self.formula(t)


_DIRECT = re.compile(r"(?i)^(?:direct(?:ly)?(?:\s+map(?:ping|ped)?)?|one[- ]to[- ]one|1\s*[:-]\s*1|as[- ]is|same(?:\s+as\s+source)?|"
                     r"copy|map|straight(?:\s+map(?:ping)?)?|pass[- ]?through|no\s+(?:transformation|change)|move)\.?$")


# ------------------------------------------------------------------ loops for repeating targets
def _add_loops(ws: MappingWorkspace, target: str, refs: list[tuple[str, FieldNode]], first: str,
               made: list[str]) -> None:
    """For-Each on repeating target ancestors whose repeating source counterpart holds the fields read."""
    if not refs:
        return
    segs_t = target.split(".")
    for i in range(1, len(segs_t)):
        anc = ".".join(segs_t[:i])
        if not anc.endswith("[]"):
            continue
        s = Structure(ws)
        if any(st.kind in LOOP_KINDS for st in s.stmts(anc, [])):
            continue
        name = segs_t[i - 1][:-2]
        hits = set()
        for sid, node in refs:
            parts = node.path.split(".")
            for j in range(len(parts) - 1, -1, -1):
                if parts[j].endswith("[]") and parts[j][:-2] == name:
                    hits.add((sid, ".".join(parts[: j + 1])))
                    break
        if len(hits) != 1:
            continue
        sid, spath = hits.pop()
        ctx = s.ancestors_ctx(anc)[1]
        select = ref_for(sid, segments(spath), ctx, first)
        if not ctx and sid == first:
            select = f"${sid}/" + select
        ws.structures.append(TargetStructure(target=anc, scope="", statements=[
            Statement(id=f"stsheet{len(ws.structures) + 1}", kind="for-each", select=select)]))
        made.append(f"For-Each on {anc.replace('[]', '')} over {select}")


def _render(marked: str, ctx: list[LoopCtx], first: str) -> str:
    def repl(m: re.Match) -> str:
        sid, path = m.group(1).split("|", 1)
        return ref_for(sid, segments(path), ctx, first)

    return re.sub(f"{_MARK}([^{_MARK}]*){_MARK}", repl, marked)


def _problems(ws: MappingWorkspace) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in analyse(ws)[1]:
        if p.target:
            out.setdefault(p.target, []).append(p.message)
    return out


# ------------------------------------------------------------------ LLM fallback
def _field_list(ws: MappingWorkspace, texts: list[str], limit: int = 300) -> str:
    words = {w.lower() for t in texts for w in re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", t)}
    rows = []
    for s in ws.sources:
        for n in flatten(s.fields):
            segs = segments(n.path)
            score = sum(2 if seg.lower() in words else 0 for seg in segs) + (1 if not n.children else 0)
            rows.append((score, f"${s.id}/{'/'.join(segs)}  ({n.type}{', repeating' if n.path.endswith('[]') else ''})"))
    rows.sort(key=lambda r: -r[0])
    return "\n".join(r[1] for r in rows[:limit])


_PROMPT = """You turn the mapping rules of a mapping sheet into formulas for a data-mapping tool. Pick the
right method from the options below (built-in function, custom function, variable, operator, literal) and write
one formula per row.

FORMULA LANGUAGE (XPath style, XSLT {version})
- Field paths: relative to the current loop item when the row has one (e.g. PmtMtd, ../PmtInfId), otherwise
  absolute with the source id ($s1/Document/CstmrCdtTrfInitn/GrpHdr/MsgId). Attributes: @Ccy.
- Literals in single quotes ('TRF'); numbers as is; empty text ''.
- Operators: = != < > <= >= and or + - * div mod ; brackets ( ).
- Variables: $name.

BUILT-IN FUNCTIONS (name: template - what it does)
{functions}
{custom}{variables}
SOURCE FIELDS (absolute; use these exact names, relative to the loop item where one is given)
{fields}

ROWS TO CONVERT
{items}

GUIDANCE
- A value written in the rule (TRF, HIGH, SEPA) is a literal in quotes; a field name is a path.
- "if X then A else B" -> if(cond, A, B); without else -> if(cond, A, ''); several cases -> when(c1, v1, c2, v2, default)
  or nested if.
- Prefer a built-in function; use a custom function only when the rule names it or nothing built-in fits.
  Use only functions listed above.{v1_note}
- A "local draft" is what the rule parser produced but was unsure about: keep it if it is right, fix it if not.
- If a row cannot be expressed, return an empty formula and say why in the explanation.
Example: rule "If PmtInf/PmtMtd = 'TRF' then map 'TRF' else map 'HIGH'", loop item $s1/Document/CstmrCdtTrfInitn/PmtInf
-> if(PmtMtd = 'TRF', 'TRF', 'HIGH')

Reply with ONLY a JSON array, one object per row, same order:
[{{"row": 1, "formula": "<formula>", "method": "<built-in | custom | variable | literal | path>", "explanation": "<short reason>"}}]"""

# Used when the request carries no catalogue (e.g. an API call without the UI).
_DEFAULT_FUNCS = [
    ("if", "if(cond, 'then', 'else')", "inline condition"), ("when", "when(c1, v1, c2, v2, 'otherwise')", "multi-branch value"),
    ("concat", "concat(a, ' ', b)", "joins strings"), ("substring", "substring(s, 1, 3)", "part of a string (1-based)"),
    ("substring-before", "substring-before(s, '-')", ""), ("substring-after", "substring-after(s, '-')", ""),
    ("upper-case", "upper-case(s)", ""), ("lower-case", "lower-case(s)", ""), ("normalize-space", "normalize-space(s)", "trim"),
    ("string-length", "string-length(s)", ""), ("contains", "contains(s, 'x')", ""), ("starts-with", "starts-with(s, 'x')", ""),
    ("translate", "translate(s, '-', '')", ""), ("replace", "replace(s, '[^0-9]', '')", "regex replace (2.0)"),
    ("number", "number(x)", ""), ("format-number", "format-number(x, '#,##0.00')", ""), ("sum", "sum(Item/Amount)", ""),
    ("count", "count(Item)", ""), ("round", "round(x)", ""), ("exists", "exists(x)", ""), ("not", "not(x)", ""),
    ("position", "position()", ""), ("current-dateTime", "current-dateTime()", ""),
    ("format-dateTime", "format-dateTime(value, 'dd/MM/yyyy')", "2.0"), ("parse-dateTime", "parse-dateTime(value, 'dd/MM/yyyy')", ""),
]


def _catalog_text(ws: MappingWorkspace, catalog: list) -> tuple[str, str, str]:
    if catalog:
        groups: dict[str, list[str]] = {}
        for f in catalog:
            groups.setdefault(f.group or "Functions", []).append(
                f"  {f.name}: {f.template}" + (f" - {f.desc}" if f.desc else ""))
        funcs = "\n".join(f"[{g}]\n" + "\n".join(lines) for g, lines in groups.items())
    else:
        funcs = "\n".join(f"  {n}: {t}" + (f" - {d}" if d else "") for n, t, d in _DEFAULT_FUNCS)
    custom = ""
    if ws.jar_functions:
        lines = [f"  {j.method_name}({', '.join(f'arg{i + 1}' for i in range(len(j.params)))}) - "
                 f"{j.class_name}.{j.method_name}({', '.join(j.params)}) : {j.ret}" + (f"  [{j.group}]" if j.group else "")
                 for j in ws.jar_functions]
        custom = "\nCUSTOM FUNCTIONS (uploaded by the user; call by method name)\n" + "\n".join(lines) + "\n"
    names = [f"  ${v.name} ({v.var_type}) = {v.transform}" for v in ws.variables if v.name]
    names += [f"  ${st.name} ({st.var_type}, local to {'/'.join(segments(t.target))}) = {st.select}"
              for t in ws.structures for st in t.statements if st.kind == "variable" and st.name]
    variables = ("\nVARIABLES\n" + "\n".join(names) + "\n") if names else ""
    return funcs, custom, variables


def _items_text(items: list[dict]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        line = f'{i}. target {it["target_x"]}'
        line += f'; loop item {it["ctx_x"]}' if it["ctx_x"] else "; not inside a loop (use absolute paths)"
        if it["source"]:
            line += f'; source column: "{it["source"]}"'
        line += f'; rule: "{it["rule"]}"'
        if it.get("draft"):
            line += f'\n   local draft: {it["draft"]}  (unsure: {it["why"]})'
        if it.get("error"):
            line += f'\n   previous answer {it["prev"]!r} was rejected: {it["error"]}'
        out.append(line)
    return "\n".join(out)


async def _ask_llm(ws: MappingWorkspace, items: list[dict], llm, catalog: list) -> list[dict]:
    funcs, custom, variables = _catalog_text(ws, catalog)
    v2 = ws.project.xslt_version == "2.0"
    prompt = _PROMPT.format(version=ws.project.xslt_version, functions=funcs, custom=custom, variables=variables,
                            fields=_field_list(ws, [it["rule"] + " " + it["source"] for it in items]),
                            items=_items_text(items),
                            v1_note="" if v2 else " XSLT 1.0 is selected: avoid 2.0-only functions.")
    reply = extract_json(await call_llm(prompt, llm))
    if isinstance(reply, dict):
        reply = reply.get("rows") or reply.get("items") or [reply]
    return reply if isinstance(reply, list) else []


def _unknown_functions(ws: MappingWorkspace, formula: str) -> list[str]:
    """Functions in a formula that are neither built in nor uploaded custom functions."""
    from app.services.transform_dsl import KNOWN_FUNCS, parse_formula, walk
    try:
        node = parse_formula(formula)
    except Exception:  # noqa: BLE001
        return []
    custom = {j.method_name.upper() for j in ws.jar_functions}
    return sorted({n.func_raw or n.func for n in walk(node)
                   if n.type == "call" and n.func not in KNOWN_FUNCS and n.func.upper() not in custom})


# ------------------------------------------------------------------ main
async def import_rows(ws: MappingWorkspace, rows: list[SheetImportRow], llm, catalog: Optional[list] = None) -> tuple[
        list[MappingRule], list[TargetStructure], list[SheetRowReport], list[str]]:
    ws = ws.model_copy(deep=True)
    first = ws.sources[0].id if ws.sources else "s1"
    mappings = {m.target: m for m in ws.mappings if not m.scope}
    reports: list[SheetRowReport] = []
    notes: list[str] = []
    loops_made: list[str] = []
    pending: list[tuple[SheetRowReport, MappingRule, str]] = []  # rows for the LLM
    seq = len(ws.mappings)

    for row in rows:
        if not row.target_path.strip():
            continue
        target = ensure_target_path(ws.target.fields, row.target_path)
        fields = Fields(ws, row.source_hint)
        rule = (row.transform or "").translate(_QUOTES).strip()
        src = (row.source_path or "").translate(_QUOTES).strip()
        comp = RuleCompiler(fields)
        marked: Optional[str] = None
        if not rule or _DIRECT.match(rule):
            marked = comp.path_or_none(src) if src else None
        else:
            marked = comp.rule(rule)
            if marked is None and src:  # e.g. rule "upper case" with a source column: let the LLM combine them
                comp.path_or_none(src)
        if not rule and not src:
            continue
        # loops from what the rule reads (also for rules only the LLM can finish: refs found so far)
        _add_loops(ws, target, comp.refs, first, loops_made)
        ctx = Structure(ws).inner_ctx(target)
        m = mappings.get(target)
        if not m:
            seq += 1
            m = MappingRule(id=f"sheet{seq}", target=target, origin="sheet")
            mappings[target] = m
            ws.mappings.append(m)
        rep = SheetRowReport(target=target, source=src, rule=row.transform or "", formula="", method="rule")
        reports.append(rep)
        if marked is not None:
            m.inputs, m.transform, m.origin, m.note = [], _render(marked, ctx, first), "sheet", None
            rep.formula = m.transform
            unclear = comp.unclear + fields.ambiguous
            if unclear:  # a formula, but the parser had to guess: let the LLM confirm or fix it
                pending.append((rep, m, "; ".join(unclear)))
        else:
            m.inputs, m.transform, m.origin = [], "", "sheet"
            pending.append((rep, m, "could not be understood"))

    # check what the local parser produced; failures go to the LLM too
    problems = _problems(ws)
    queued = {rep.target for rep, _m, _w in pending}
    for rep in reports:
        if rep.formula and problems.get(rep.target) and rep.target not in queued:
            m = mappings[rep.target]
            pending.append((rep, m, "; ".join(problems[rep.target])))

    if pending:
        await _llm_round(ws, pending, llm, notes, mappings, catalog or [])

    for rep in reports:
        m = mappings[rep.target]
        if rep.method == "review" and not m.note:
            m.note = rep.note
    notes += [f"{r.target}: {r.note}" for r in reports if r.method == "review"]
    if loops_made:
        notes.append("Added " + "; ".join(loops_made) + ".")
    new_structs = [s for s in ws.structures if any(st.id.startswith("stsheet") for st in s.statements)]
    return list(mappings.values()), new_structs, reports, notes


async def _llm_round(ws: MappingWorkspace, pending: list, llm, notes: list[str], mappings: dict, catalog: list) -> None:
    first = ws.sources[0].id if ws.sources else "s1"
    s = Structure(ws)
    items = []
    for rep, m, why in pending:
        ctx = s.inner_ctx(rep.target)
        items.append({"rep": rep, "m": m, "why": why, "target_x": "/" + "/".join(segments(rep.target)),
                      "ctx_x": (f"${ctx[-1].source_id}/" + "/".join(segments(ctx[-1].path))) if ctx else "",
                      "rule": rep.rule.translate(_QUOTES), "source": rep.source, "prev": rep.formula,
                      "draft": rep.formula})
    try:
        for attempt in range(2):
            todo = [it for it in items if not it.get("done")]
            if not todo:
                break
            answers = await _ask_llm(ws, todo, llm, catalog)
            for i, it in enumerate(todo):
                ans = next((a for a in answers if isinstance(a, dict) and a.get("row") == i + 1),
                           answers[i] if i < len(answers) and isinstance(answers[i], dict) else {})
                formula = str(ans.get("formula") or "").translate(_QUOTES).strip()
                it["m"].transform = formula
                it["explanation"] = str(ans.get("explanation") or "").strip()
                it["method"] = str(ans.get("method") or "").strip()
            probs = _problems(ws)
            for it in todo:
                f, err = it["m"].transform, None
                if not f:
                    err = "the AI could not express this rule"
                else:
                    bad = check_formula(f)
                    err = f"invalid formula ({bad})" if bad else None
                    unknown = [] if err else _unknown_functions(ws, f)
                    if unknown:
                        err = f"unknown function(s) {', '.join(unknown)}: use only the listed functions"
                    err = err or ("; ".join(probs[it["rep"].target]) if probs.get(it["rep"].target) else None)
                if err:
                    it["error"], it["prev"] = err, f
                else:
                    it["done"] = True
        for it in items:
            rep, m = it["rep"], it["m"]
            if it.get("done"):
                same = it["draft"] and m.transform.replace(" ", "") == it["draft"].replace(" ", "")
                rep.method, m.origin = ("rule", "sheet") if same else ("ai", "ai")
                how = f" [{it['method']}]" if it.get("method") else ""
                rep.note = ("AI confirmed the parsed formula" if same else "") + \
                    (": " if same and it.get("explanation") else "") + (it.get("explanation") or "Mapped by the AI assistant.") + how
                m.note = f"AI: {rep.note}"
            else:
                rep.method = "review"
                if it["draft"]:  # keep the parser's formula rather than a rejected AI answer
                    m.transform = it["draft"]
                    rep.note = f"Needs review — kept the parsed formula ({it['why']}); AI: {it.get('error') or 'no better answer'}."
                else:
                    rep.note = f"Needs review — {it.get('error') or it['why']}."
            rep.formula = m.transform
    except LlmError as exc:
        _llm_failed(pending, f"AI fallback unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001
        _llm_failed(pending, f"AI fallback failed: {exc}")


def _llm_failed(pending: list, msg: str) -> None:
    for rep, m, why in pending:
        m.transform = rep.formula  # the parser's draft (if any), not a half-finished AI answer
        rep.method = "review"
        rep.note = (f"Needs review — kept the parsed formula ({why}). {msg}" if rep.formula
                    else f"Needs review — {why}. {msg}")
        m.note = rep.note

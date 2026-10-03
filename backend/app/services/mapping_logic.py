"""
Field-path resolution + the mapping-sheet instruction compiler.

A mapping sheet's "source path" or "transform" column often contains
XPath-style references (slashes, an extra namespace/root prefix) or plain
instructional prose ("Map from GrpHdr/MsgId") rather than the app's own
{0}/{1} DSL. This module turns that into real, resolved mappings instead of
baking the raw text into generated code as a string literal.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.schemas import FieldNode, MappingRule, SourceRef, SourceSpec, ValidationIssue
from app.services.parsers import flatten
from app.services.transform_dsl import KNOWN_FUNCS, max_placeholder_index, parse_expr


def to_dot_path(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"^[/.]+", "", s)
    s = re.sub(r"[/\\]+", ".", s)
    s = re.sub(r"\.+", ".", s)
    s = s.replace("[]", "")
    return s


def norm_key(path: str) -> str:
    return to_dot_path(path).lower()


def resolve_field_path(raw_path: str, candidates: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
    """candidates: list of (source_id_or_empty, path). Returns the matched
    (source_id, path) using exact match, then fuzzy suffix matching in
    either direction, then a last-resort unique last-segment match."""
    norm = norm_key(raw_path)
    if not norm:
        return None
    for sid, path in candidates:
        if norm_key(path) == norm:
            return sid, path
    for sid, path in candidates:
        if norm_key(path).endswith("." + norm):
            return sid, path
    for sid, path in candidates:
        if norm.endswith("." + norm_key(path)):
            return sid, path
    last_seg = norm.split(".")[-1]
    matches = [(sid, path) for sid, path in candidates if norm_key(path).split(".")[-1] == last_seg]
    if len(matches) == 1:
        return matches[0]
    return None


def build_candidate_nodes(sources: list[SourceSpec], source_hint: Optional[str]) -> list[tuple[str, str]]:
    chosen = sources
    if source_hint:
        match = [s for s in sources if s.id == source_hint or s.label.lower() == source_hint.lower()]
        if match:
            chosen = match
    out: list[tuple[str, str]] = []
    for s in chosen:
        for n in flatten(s.fields):
            out.append((s.id, n.path))
    return out


XPATH_FUNC_MAP = {
    "concat": "CONCAT", "substring": "SUBSTRING", "string-length": "STRINGLENGTH",
    "contains": "CONTAINS", "starts-with": "STARTSWITH", "normalize-space": "TRIM", "trim": "TRIM",
    "upper": "UPPERCASE", "upper-case": "UPPERCASE", "uppercase": "UPPERCASE",
    "lower": "LOWERCASE", "lower-case": "LOWERCASE", "lowercase": "LOWERCASE",
    "if": "IF", "choose": "WHEN", "when": "WHEN",
}

_PREFIX_RE = re.compile(
    r"^\s*(map(?:ped)?\s+from|copy\s+of|copy\s+from|direct\s+map(?:ping)?(?:\s+from)?|"
    r"set\s+(?:to|equal\s+to)|value\s+of|=|:)\s*", re.IGNORECASE)
_PATH_LIKE_RE = re.compile(r"^[A-Za-z_][\w:-]*(?:[./][A-Za-z_][\w:-]*)+$")
_ARGS_SPLIT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*\((.*)\)$", re.S)


def strip_instruction_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text).strip()


def looks_like_path(tok: str) -> bool:
    return bool(_PATH_LIKE_RE.match(tok))


def _split_top_level_args(s: str) -> list[str]:
    args: list[str] = []
    cur = ""
    in_quote = False
    depth = 0
    for c in s:
        if c == "'":
            in_quote = not in_quote
            cur += c
            continue
        if not in_quote:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
                continue
        cur += c
    if cur.strip():
        args.append(cur.strip())
    return args


def compile_expr_text(text: str, candidates: list[tuple[str, str]], inputs_acc: list[SourceRef]) -> str:
    text = text.strip()
    m = re.match(r"^'(.*)'$", text, re.S) or re.match(r'^"(.*)"$', text, re.S)
    if m:
        return "'" + m.group(1).replace("'", "\\'") + "'"
    m = _ARGS_SPLIT_RE.match(text)
    if m:
        dsl_func = XPATH_FUNC_MAP.get(m.group(1).lower(), m.group(1).upper())
        args = [compile_expr_text(a, candidates, inputs_acc) for a in _split_top_level_args(m.group(2))]
        return f"{dsl_func}({', '.join(args)})"
    if looks_like_path(text):
        hit = resolve_field_path(text, candidates)
        if hit:
            sid, path = hit
            idx = next((i for i, r in enumerate(inputs_acc) if r.source_id == sid and r.path == path), -1)
            if idx == -1:
                inputs_acc.append(SourceRef(source_id=sid, path=path))
                idx = len(inputs_acc) - 1
            return f"{{{idx}}}"
    if re.match(r"^-?\d+(\.\d+)?$", text):
        return text
    return "'" + text.replace("'", "\\'") + "'"


def compile_sheet_row(source_path_cell: str, transform_cell: str,
                       candidates: list[tuple[str, str]]) -> tuple[list[SourceRef], str, str]:
    """Returns (inputs, transform, note)."""
    inputs_acc: list[SourceRef] = []
    transform_str = ""
    note = ""
    sp = (source_path_cell or "").strip()
    tf = (transform_cell or "").strip()

    if sp:
        hit = resolve_field_path(sp, candidates)
        if hit:
            inputs_acc.append(SourceRef(source_id=hit[0], path=hit[1]))
        else:
            note += f'Could not resolve source path "{sp}" against the source tree. '

    if tf:
        stripped = strip_instruction_prefix(tf)
        compiled = compile_expr_text(stripped, candidates, inputs_acc)
        if re.match(r"^\{\d+\}$", compiled):
            transform_str = ""
        elif re.match(r"^'.*'$", compiled, re.S) and not looks_like_path(stripped):
            note += (f'Could not parse instruction "{tf}" into a field reference or known function '
                      "— review this mapping manually. ")
        else:
            transform_str = compiled

    return inputs_acc, transform_str, note.strip()


def ensure_target_path(target_tree: list[FieldNode], raw_path: str) -> str:
    """Finds an existing target field matching raw_path (fuzzy), or creates
    the missing nested fields so there's always a real node to map onto."""
    dot_path = to_dot_path(raw_path)
    existing = resolve_field_path(dot_path, [("", n.path) for n in flatten(target_tree)])
    if existing:
        return existing[1]
    segs = dot_path.split(".")
    arr = target_tree
    cur_path = ""
    for i, seg in enumerate(segs):
        cur_path = f"{cur_path}.{seg}" if cur_path else seg
        node = next((n for n in arr if n.name.rstrip("[]").lower() == seg.lower()), None)
        if node is None:
            node = FieldNode(name=seg, path=cur_path, type=("string" if i == len(segs) - 1 else "object"),
                              mandatory=False, children=[])
            arr.append(node)
        else:
            cur_path = node.path
        arr = node.children
    return cur_path


def validate_mappings(target_fields: list[FieldNode], mandatory_overrides: dict[str, bool],
                       mappings: list[MappingRule]) -> tuple[list[str], list[str], list[ValidationIssue]]:
    mapped = {m.target for m in mappings if m.inputs or m.transform.strip()}

    def is_mandatory(f: FieldNode) -> bool:
        return mandatory_overrides.get(f.path, f.mandatory)

    unmapped_mandatory = [f.path for f in target_fields if is_mandatory(f) and f.path not in mapped]
    unmapped_optional = [f.path for f in target_fields if not is_mandatory(f) and f.path not in mapped]

    issues: list[ValidationIssue] = []
    for m in mappings:
        node = parse_expr(m.transform)
        if node.error:
            issues.append(ValidationIssue(target=m.target, severity="error",
                                          message=f"formula error: {node.error}"))
        max_idx = max_placeholder_index(node)
        if max_idx >= len(m.inputs):
            issues.append(ValidationIssue(
                target=m.target, severity="error",
                message=f'transform references {{{max_idx}}} but only {len(m.inputs)} input(s) are mapped.'))
        if node.type == "call" and node.func not in KNOWN_FUNCS:
            issues.append(ValidationIssue(
                target=m.target, severity="warning",
                message=f"uses custom function {node.func_raw}() — a stub is generated in CustomFunctions.java."))
        if not m.inputs and not m.transform.strip():
            issues.append(ValidationIssue(target=m.target, severity="error", message="has no source input."))

    return unmapped_mandatory, unmapped_optional, issues

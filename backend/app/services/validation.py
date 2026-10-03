"""
Validate screen: does the mapping produce a valid target document?

1. Coverage — every target field (leaf) is mapped (directly, inside any
   [When]/[Otherwise] branch, or through an ancestor's Copy-Of) or not.
   Mandatory means: required by the XSD *and* its parent element is written
   (a mandatory child of an optional, unmapped element isn't required).
   Unpicked xs:choice alternatives don't count.
2. Problems — the same per-row checks as the red markers in the tree.
3. XSD — if a sample input is available, the generated XSLT is run on it and
   the output is validated against the target XSD (lxml XMLSchema).
"""
from __future__ import annotations

import re

from app.models.schemas import (
    FieldNode, FullValidationRequest, FullValidationResponse, RowProblem, XsdCheck, XsdErrorDetail,
)
from app.services.links import walk_mapping
from app.services.structure import Structure
from app.services.test_run import TestRunError, run_xslt
from app.services.xslt_gen import generate_xslt


def validate_full(req: FullValidationRequest) -> FullValidationResponse:
    ws = req.workspace
    s = Structure(ws)
    w = walk_mapping(ws)
    problems = list(w.problems)
    copied = w.copied_paths
    any_mapped = bool(ws.mappings or ws.structures)
    total = mapped = 0
    mand: list[str] = []
    opt: list[str] = []

    def bare(n: FieldNode) -> str:
        return n.name[:-2] if n.name.endswith("[]") else n.name

    def walk(nodes: list[FieldNode], parent_written: bool) -> None:
        nonlocal total, mapped
        for n in nodes:
            if s.excluded(n):
                continue
            here = s.has_content(n) or n.path in copied
            required = s.is_mandatory(n) and parent_written
            written = here or required
            if not n.children:
                total += 1
                if here:
                    mapped += 1
                elif required:
                    mand.append(n.path)
                else:
                    opt.append(n.path)
                continue
            if required and not here and not any(s.is_mandatory(c) for c in n.children if not s.excluded(c)):
                mand.append(n.path)  # e.g. a mandatory element that only holds a choice
            if written:
                for g in dict.fromkeys(c.choice for c in n.children if c.choice):
                    alts = [c for c in n.children if c.choice == g]
                    if not any(s.has_content(a) or a.path in copied for a in alts) and not s.choice_sel.get(g):
                        problems.append(RowProblem(row_key=f"e|{n.path}|", target=n.path,
                                                   message="Choice: map one of " + " | ".join(bare(a) for a in alts)))
            walk(n.children, written)

    walk(ws.target.fields, any_mapped)
    xsd = _xsd_check(req)
    valid = not mand and not problems and (xsd.valid if xsd.ran else True)
    return FullValidationResponse(valid=valid, total_fields=total, mapped_fields=mapped,
                                  unmapped_mandatory=mand, unmapped_optional=opt, problems=problems, xsd=xsd)


def _xsd_check(req: FullValidationRequest) -> XsdCheck:
    ws = req.workspace
    if ws.target.type != "xsd":
        return XsdCheck(reason="The target is not an XSD.")
    if not (req.target_xsd or "").strip():
        return XsdCheck(reason="Target XSD text isn't available — re-load the target schema.")
    first = ws.sources[0] if ws.sources else None
    sample = (req.sample_inputs.get(first.id) or "").strip() if first else ""
    if not sample:
        return XsdCheck(reason="Paste a sample input in Test / Run to also validate the generated output against the target XSD.")
    try:
        from lxml import etree
    except ImportError:
        return XsdCheck(reason="lxml is not installed on the backend (pip install -r requirements.txt).")
    try:
        schema = etree.XMLSchema(etree.fromstring(req.target_xsd.strip().encode("utf-8")))
    except (etree.XMLSchemaParseError, etree.XMLSyntaxError) as exc:
        return XsdCheck(reason=f"Could not load the target XSD: {exc}")
    try:
        output, _warnings = run_xslt(generate_xslt(ws), ws, req.sample_inputs)
    except TestRunError as exc:
        return XsdCheck(ran=True, valid=False, engine="xslt", errors=[f"XSLT could not run: {exc}"])
    try:
        doc = etree.fromstring(output.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return XsdCheck(ran=True, valid=False, engine="xslt", errors=[f"Output is not well-formed XML: {exc}"], output=output)
    ok = schema.validate(doc)
    log = list(schema.error_log)[:200]
    errors = [f"line {e.line}: {e.message}" for e in log]
    details = [_explain(e.line, e.message, doc, ws, sample) for e in log]
    check = XsdCheck(ran=True, valid=ok, engine="xslt", errors=errors, details=details, output=output)
    _check_source(req, sample, check)
    return check


def _check_source(req: FullValidationRequest, sample: str, check: XsdCheck) -> None:
    """Validates the sample input against the source XSD."""
    if not (req.source_xsd or "").strip():
        return
    from lxml import etree
    try:
        schema = etree.XMLSchema(etree.fromstring(req.source_xsd.strip().encode("utf-8")))
        doc = etree.fromstring(sample.encode("utf-8"))
    except (etree.XMLSchemaParseError, etree.XMLSyntaxError):
        return
    check.source_checked = True
    check.source_valid = schema.validate(doc)
    check.source_errors = [f"line {e.line}: {_short(e.message)}" for e in list(schema.error_log)[:100]]


def _short(msg: str) -> str:
    return re.sub(r"\{[^}]*\}", "", msg)


def _explain(line: int, message: str, doc, ws, sample: str) -> XsdErrorDetail:
    """Turns a schema error into: which target field, its formula, and a likely cause."""
    from lxml import etree

    msg = _short(message)
    m = re.search(r"Element '([^']+)'", msg)
    name = m.group(1) if m else ""
    el = next((e for e in doc.iter() if isinstance(e.tag, str) and e.sourceline == line
               and etree.QName(e).localname == name), None)
    target = ""
    if el is not None:
        names = [etree.QName(a).localname for a in reversed(list(el.iterancestors()))] + [name]
        target = _target_path(ws.target.fields, names) or ""
    formula = ""
    if target:
        rule = next((r for r in ws.mappings if r.target == target and not r.scope), None) or \
            next((r for r in ws.mappings if r.target == target), None)
        if rule:
            formula = rule.transform or (f"${rule.inputs[0].source_id}/" + rule.inputs[0].path.replace("[]", "").replace(".", "/")
                                         if rule.inputs else "")
    hint = ""
    if "is not a valid value" in msg and "''" in msg:
        if not formula:
            hint = "The field is written empty: it is mandatory but nothing is mapped to it."
        elif _sample_has(formula, ws, sample) is False:
            hint = (f"The Test / Run sample has no value at {formula}, so the mandatory field is written empty. "
                    "Add it to the sample, or map the field from a path / default that has a value.")
        else:
            hint = "The formula produced an empty value for this sample."
    elif "is not a valid value" in msg:
        hint = "The value doesn't match the target type/format — check the formula (e.g. a date pattern)."
    elif "Missing child element" in msg:
        exp = re.search(r"Expected is (?:one of )?\(\s*([^)]*)\)", msg)
        opts = [o.strip() for o in exp.group(1).split(",")] if exp else []
        hint = (f"Map one of: {' | '.join(opts)} (it is a choice)." if "one of" in msg and len(opts) > 1
                else f"Map {', '.join(opts) or 'the missing child'} under this element.")
        if target and opts:
            hint += _choice_detail(target, opts, ws, sample)
    elif "This element is not expected" in msg:
        hint = "An element is written that the target schema doesn't allow here (often a Copy-Of of a differently shaped source)."
    return XsdErrorDetail(line=line, message=msg, target=target, formula=formula, hint=hint)


def _rule_formula(rule) -> str:
    if rule.transform:
        return rule.transform
    if rule.inputs:
        return f"${rule.inputs[0].source_id}/" + rule.inputs[0].path.replace("[]", "").replace(".", "/")
    return ""


def _choice_detail(target: str, opts: list[str], ws, sample: str) -> str:
    """Which options are mapped, and which ones the sample really has."""
    mapped, empty, unmapped = [], [], []
    for o in opts:
        tp = f"{target}.{o}"
        rule = next((r for r in ws.mappings if r.target == tp or r.target.startswith(tp + ".")), None)
        if rule is None:
            unmapped.append(o)
            continue
        has = _sample_has(_rule_formula(rule), ws, sample)
        (empty if has is False else mapped).append(o)
    parts = []
    if empty:
        parts.append(f"{', '.join(empty)} is mapped but the sample has no value for it")
    if unmapped:
        parts.append(f"{', '.join(unmapped)} is not mapped")
    present = []
    src_base = next((_rule_formula(r) for r in ws.mappings if r.target.startswith(target + ".")), "")
    if src_base and "/" in src_base:
        base = src_base.rsplit("/", 1)[0]
        present = [o for o in unmapped if _sample_has(f"{base}/{o}", ws, sample)]
    if present:
        parts.append(f"the sample contains {', '.join(present)} — map it too (or Copy-Of the parent)")
    return (" " + "; ".join(parts) + ".") if parts else ""


def _target_path(nodes: list[FieldNode], names: list[str]) -> str | None:
    cur, path = nodes, None
    for n in names:
        hit = next((x for x in cur if (x.name[:-2] if x.name.endswith("[]") else x.name) == n), None)
        if hit is None:
            return path
        path, cur = hit.path, hit.children
    return path


def _sample_has(formula: str, ws, sample: str):
    """True/False whether an absolute $s1/... path has a non-empty value in the sample; None if unknown."""
    from app.services.test_run import Evaluator, _load_source, _text
    from app.services.transform_dsl import parse_expr

    node = parse_expr(formula)
    if node.type != "ref" or not node.absolute:
        return None
    try:
        first = ws.sources[0]
        ev = Evaluator(ws, {first.id: _load_source(first.type, sample, first.csv_header_row, first.fields)})
        locs = ev.locate_ref(node, [])
    except Exception:  # noqa: BLE001
        return None
    return any(str(_text(n) or "").strip() for n, _ in locs)

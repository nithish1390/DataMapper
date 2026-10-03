"""
Powers the Test/Run tab. Two engines, picked from a dropdown in the UI:

- "xslt": runs the *generated XSLT* (exactly what the XSLT tab shows) with
  lxml against the first source's sample XML — a true execution.
- "processor": evaluates the mapping rules directly (the same rules the
  generated MapStruct processor encodes), including for-each / if / choose /
  copy-of statements, without compiling the Java project.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional
from xml.sax.saxutils import escape, quoteattr

from app.services import fixed_width, swift_mt
from app.models.schemas import FieldNode, MappingWorkspace, SourceRef, Statement
from app.services.structure import (
    LoopCtx, Structure, branch_key, copy_pairs, has_element_children, is_attribute, otherwise_key, relative_to_context,
)
from app.services.transform_dsl import EvalEnv, ExprNode, _truthy, eval_expr, parse_expr


class TestRunError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


# ---------------------------------------------------------------- inputs
def _load_source(fmt: str, text: str, csv_header_row: Optional[int] = None,
                 fields: Optional[list[FieldNode]] = None) -> Any:
    """Source document as either an ET root element (XML) or plain dict/list data (JSON / YAML,
    CSV row, SWIFT fields) — read the same way the parsers build the field tree."""
    from app.services.parsers import ROOT_ARRAY, csv_table
    if fmt in ("xsd", "xml") or text.lstrip().startswith("<"):
        try:
            return ET.fromstring(text.strip())
        except ET.ParseError as exc:
            raise TestRunError(f"Sample is not valid XML: {exc}") from exc
    if fmt == "fixed":
        return fixed_width.read_record(text, fields or [])
    if fmt == "csv":
        try:
            headers, data, _used = csv_table(text, csv_header_row)
        except ValueError as exc:
            raise TestRunError(f"CSV sample: {exc}") from exc
        row = data[0] if data else []
        return {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(headers)}
    if fmt == "swift":
        from app.services.swift_mt import extract_values
        return extract_values(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise TestRunError(f"Sample is not valid JSON: {exc}") from exc
    return {ROOT_ARRAY: data} if isinstance(data, list) else data


def _children(node: Any, name: str) -> list[Any]:
    if isinstance(node, ET.Element):
        return [c for c in node if _local(c.tag) == name]
    if isinstance(node, dict):
        v = node.get(name)
        if v is None:
            return []
        return list(v) if isinstance(v, list) else [v]
    return []


def _text(node: Any) -> Any:
    if isinstance(node, _DocRoot):
        return _text(node.doc)
    if isinstance(node, ET.Element):
        return "".join(node.itertext()) if len(node) else (node.text or "")
    if isinstance(node, dict) and "Value" in node:
        return node["Value"]  # a composite SWIFT field read as a whole: its raw value
    if isinstance(node, (dict, list)):
        return json.dumps(node)
    return node


# ---------------------------------------------------------------- output
@dataclass
class Out:
    name: str
    text: Optional[str] = None
    children: list["Out"] = field(default_factory=list)


def _from_source(node: Any, name: str) -> Out:
    if isinstance(node, ET.Element):
        o = Out(_local(node.tag), text=(node.text or "").strip() or None)
        o.children = [Out("@" + _local(k), text=v) for k, v in node.attrib.items()
                      if not k.startswith("{http://www.w3.org/2001/XMLSchema-instance}")]
        o.children += [_from_source(c, "") for c in node]
        return o
    if isinstance(node, dict):
        o = Out(name)
        for k, v in node.items():
            for item in (v if isinstance(v, list) else [v]):
                o.children.append(_from_source(item, k))
        return o
    return Out(name, text="" if node is None else str(node))


def _xml(outs: list[Out], depth: int, ns: Optional[str]) -> str:
    lines = []
    for o in outs:
        ind = "  " * depth
        attrs = (f' xmlns="{ns}"' if ns and depth == 0 else "") + "".join(
            f" {a.name[1:]}={quoteattr(a.text or '')}" for a in o.children if a.name.startswith("@"))
        kids = [c for c in o.children if not c.name.startswith("@")]
        if kids:
            lines.append(f"{ind}<{o.name}{attrs}>")
            lines.append(_xml(kids, depth + 1, ns))
            lines.append(f"{ind}</{o.name}>")
        elif o.text:
            lines.append(f"{ind}<{o.name}{attrs}>{escape(o.text)}</{o.name}>")
        else:
            lines.append(f"{ind}<{o.name}{attrs}/>")
    return "\n".join(lines)


def _json(outs: list[Out], array_names: set[str]) -> dict:
    result: dict[str, Any] = {}
    for o in outs:
        val: Any = _json(o.children, array_names) if o.children else o.text
        if o.children and o.text is not None:
            val["#text"] = o.text  # element with attributes and a value
        if o.name in result or o.name in array_names:
            existing = result.get(o.name)
            if existing is None:
                result[o.name] = [val]
            elif isinstance(existing, list) and o.name in array_names:
                existing.append(val)
            else:
                result[o.name] = [existing, val]
        else:
            result[o.name] = val
    return result


# ------------------------------------------------------------- evaluator
class _DocRoot:
    """Virtual parent of an XML document element, so absolute paths start with its tag."""

    def __init__(self, doc: ET.Element):
        self.doc = doc


Loc = tuple[Any, tuple]  # (node, ancestors from the root)


class Evaluator(EvalEnv):
    def __init__(self, ws: MappingWorkspace, docs: dict[str, Any]):
        self.ws = ws
        self.s = Structure(ws)
        self.docs = docs
        self.vars: dict[str, Any] = {}
        self.items: dict[LoopCtx, tuple[Loc, int, int]] = {}  # loop -> (item, index, count)
        self.groups: dict[LoopCtx, tuple[list[Loc], Any]] = {}  # for-each-group -> (members, key)
        self.node_vars: dict[str, list[Loc]] = {}  # node-typed variables
        self.cur: list[LoopCtx] = []

    # ------------------------------------------------------- navigation
    def _root(self, source_id: str) -> list[Loc]:
        doc = self.docs.get(source_id)
        if doc is None:
            return []
        return [(_DocRoot(doc) if isinstance(doc, ET.Element) else doc, ())]

    @staticmethod
    def _step(locs: list[Loc], step: str) -> list[Loc]:
        if step == ".":
            return locs
        if step == "..":
            return [(parents[-1], parents[:-1]) for _, parents in locs if parents]
        out: list[Loc] = []
        for node, parents in locs:
            if step.startswith("@"):
                if isinstance(node, ET.Element) and node.get(step[1:]) is not None:
                    out.append((node.get(step[1:]), parents + (node,)))
                continue
            if isinstance(node, _DocRoot):
                kids = [node.doc] if _local(node.doc.tag) == step else []
            else:
                kids = _children(node, step)
            out.extend((k, parents + (node,)) for k in kids)
        return out

    def locate_ref(self, ref: ExprNode, ctx: list[LoopCtx]) -> list[Loc]:
        if ref.absolute and ref.source_id in self.node_vars and ref.source_id not in self.s.source_ids:
            locs = list(self.node_vars[ref.source_id])  # $party/Name
            for step in ref.steps:
                locs = self._step(locs, step)
            return locs
        if ref.group:  # current-group()/...
            loop = next((c for c in reversed(ctx) if c in self.groups), None)
            locs = list(self.groups[loop][0]) if loop else []
            for step in ref.steps:
                locs = self._step(locs, step)
            return locs
        if ref.absolute:
            sid = ref.source_id if ref.source_id in self.s.source_ids else self.s.first_source()
            locs = self._root(sid)
        elif ctx and ctx[-1] in self.items:
            locs = [self.items[ctx[-1]][0]]
        else:
            locs = self._root(self.s.first_source())
        for step in ref.steps:
            locs = self._step(locs, step)
        return locs

    def locate_input(self, ref: SourceRef, ctx: list[LoopCtx]) -> list[Loc]:
        loop, segs = relative_to_context(ref, ctx)
        locs = [self.items[loop][0]] if loop is not None and loop in self.items else self._root(ref.source_id)
        for seg in segs:
            locs = self._step(locs, seg)
        return locs

    def locate(self, expr: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx]) -> list[Loc]:
        if expr.type == "var" and expr.name in self.node_vars:
            return list(self.node_vars[expr.name])
        if expr.type == "placeholder":
            return self.locate_input(inputs[expr.index], ctx) if expr.index < len(inputs) else []
        if expr.type == "ref":
            return self.locate_ref(expr, ctx)
        return []

    # ------------------------------------------------------ EvalEnv hooks
    def ref_nodes(self, node: ExprNode) -> list[Any]:
        return [n for n, _ in self.locate_ref(node, self.cur)]

    def node_text(self, n: Any) -> Any:
        return _text(n)

    def position(self) -> int:
        return self.items[self.cur[-1]][1] + 1 if self.cur and self.cur[-1] in self.items else 1

    def last(self) -> int:
        return self.items[self.cur[-1]][2] if self.cur and self.cur[-1] in self.items else 1

    def var_nodes(self, name: str):
        locs = self.node_vars.get(name)
        return [n for n, _ in locs] if locs is not None else None

    def assign(self, name: str, var_type: str, text: str, inputs: list[SourceRef], ctx: list[LoopCtx]) -> None:
        """Evaluates a variable and converts it to its data type (same rules as the XSLT)."""
        expr = parse_expr(text if text.strip() else ("{0}" if inputs else "''"))
        if var_type == "node":
            locs = self.locate(expr, inputs, ctx)
            if expr.type == "var" and expr.name in self.node_vars:
                locs = list(self.node_vars[expr.name])
            self.node_vars[name] = locs
            self.vars[name] = _text(locs[0][0]) if locs else ""
            return
        self.node_vars.pop(name, None)
        self.vars[name] = _cast(self.evaluate(expr, inputs, ctx), var_type)

    def grouping_key(self) -> Any:
        loop = next((c for c in reversed(self.cur) if c in self.groups), None)
        return self.groups[loop][1] if loop else None

    # ------------------------------------------------------ expressions
    def evaluate(self, expr: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx]) -> Any:
        self.cur = ctx
        values = []
        for i in inputs:
            locs = self.locate_input(i, ctx)
            values.append(_text(locs[0][0]) if locs else None)
        return eval_expr(expr, values, self.vars, self)

    def test(self, text: str, inputs: list[SourceRef], ctx: list[LoopCtx]) -> bool:
        if not text.strip():
            return bool(inputs) and bool(self.locate_input(inputs[0], ctx))
        return _truthy(self.evaluate(parse_expr(text), inputs, ctx))

    # ------------------------------------------------------------ tree
    def nodes(self, nodes: list[FieldNode], ctx: list[LoopCtx], scopes: list[str]) -> list[Out]:
        out: list[Out] = []
        for n in nodes:
            if self.s.has_content(n):
                out.extend(self.wrap(n, self.s.stmts(n.path, scopes), ctx, scopes, None))
        return out

    def wrap(self, n: FieldNode, stmts: list[Statement], ctx: list[LoopCtx], scopes: list[str],
             override: Optional[tuple[Statement, str]]) -> list[Out]:
        if not stmts:
            return self.element(n, ctx, scopes, override)
        st, rest = stmts[0], stmts[1:]
        if st.kind == "for-each":
            sel = self.s.select_expr(st)
            loop = self.s.loop_for(st, ctx)
            if sel is None or loop is None:
                return self.wrap(n, rest, ctx, scopes, override)
            items = self.locate(sel, st.inputs, ctx)
            out: list[Out] = []
            saved = self.items.get(loop)
            for idx, item in enumerate(items):
                self.items[loop] = (item, idx, len(items))
                out.extend(self.wrap(n, rest, ctx + [loop], scopes, override))
            if saved is not None:
                self.items[loop] = saved
            else:
                self.items.pop(loop, None)
            return out
        if st.kind == "variable":
            if st.name:
                self.assign(st.name, st.var_type, st.select, st.inputs, ctx)
            return self.wrap(n, rest, ctx, scopes, override)
        if st.kind == "for-each-group":
            sel = self.s.select_expr(st)
            loop = self.s.loop_for(st, ctx)
            if sel is None or loop is None:
                return self.wrap(n, rest, ctx, scopes, override)
            key_expr = parse_expr(st.group_by or ".")
            groups: dict[str, list[Loc]] = {}
            keys: dict[str, Any] = {}
            saved = self.items.get(loop)
            members = self.locate(sel, st.inputs, ctx)
            for idx, item in enumerate(members):  # group-by, groups in order of first appearance
                self.items[loop] = (item, idx, len(members))
                k = self.evaluate(key_expr, [], ctx + [loop])
                ks = _str(k) or ""
                groups.setdefault(ks, []).append(item)
                keys.setdefault(ks, k)
            out: list[Out] = []
            for gi, (ks, locs) in enumerate(groups.items()):
                self.items[loop] = (locs[0], gi, len(groups))
                self.groups[loop] = (locs, keys[ks])
                out.extend(self.wrap(n, rest, ctx + [loop], scopes, override))
            self.groups.pop(loop, None)
            if saved is not None:
                self.items[loop] = saved
            else:
                self.items.pop(loop, None)
            return out
        if st.kind == "if":
            return self.wrap(n, rest, ctx, scopes, override) if self.test(st.test, st.inputs, ctx) else []
        for i, w in enumerate(st.whens):
            if self.test(w.test, st.inputs, ctx):
                return self.wrap(n, rest, ctx, scopes + [branch_key(st, i)],
                                 (st, w.value) if w.value.strip() else override)
        if st.otherwise is not None:
            return self.wrap(n, rest, ctx, scopes + [otherwise_key(st)],
                             (st, st.otherwise) if st.otherwise.strip() else override)
        return []

    def element(self, n: FieldNode, ctx: list[LoopCtx], scopes: list[str],
                override: Optional[tuple[Statement, str]]) -> list[Out]:
        tag = n.name[:-2] if n.name.endswith("[]") else n.name
        m = self.s.mapping_for(n.path, scopes)
        if override is not None and not n.children:
            st, text = override
            return [Out(tag, text=_str(self.evaluate(parse_expr(text), st.inputs, ctx)))]
        if self.s.is_copy(m, n):
            locs = self.locate(self.s.mapping_expr(m), m.inputs, ctx)
            found = self.s.copy_source(m, ctx)
            if found is None:  # source element unknown to the tree: raw copy
                if not locs:
                    return [Out(tag)]
                src = _from_source(locs[0][0], tag)
                return [Out(tag, text=src.text, children=src.children)]
            if not locs:
                return [Out(tag)]
            text, kids = self.copy_struct(n, locs[0], found[1], ctx, scopes)
            return [Out(tag, text=text, children=kids)]
        if n.children:
            items = self.s.guard_items(n, scopes)
            if items and not any(
                    (self.locate_ref(it, ctx) if isinstance(it, ExprNode) else self.locate_input(it, ctx))
                    for it, _m in items):
                return []
            kids = self.nodes(n.children, ctx, scopes)
            text = _str(self.evaluate(self.s.mapping_expr(m), m.inputs, ctx)) if m else None
            if not kids and text is None:
                # Mandatory (or statement-wrapped) elements are always written, as in the XSLT.
                return [Out(tag)] if self.s.stmts(n.path, scopes) or self.s.is_mandatory(n) else []
            return [Out(tag, text=text, children=kids)]
        if not m:
            return []
        expr = self.s.mapping_expr(m)
        if expr.type in ("ref", "placeholder") and not self.s.is_mandatory(n) \
                and not self.locate(expr, m.inputs, ctx):
            return []
        return [Out(tag, text=_str(self.evaluate(expr, m.inputs, ctx)))]

    def copy_struct(self, tgt: FieldNode, loc: Loc, src: FieldNode, ctx: list[LoopCtx],
                    scopes: list[str]) -> tuple[Optional[str], list[Out]]:
        """Mirror of XsltWriter.copy_struct: (own text, children) built along the target schema."""
        kids: list[Out] = []
        pairs, _spare = copy_pairs(tgt, src)
        for tc, sc, _fuzzy in pairs:
            if self.s.excluded(tc):
                continue
            if self.s.mapping_for(tc.path, scopes) or self.s.stmts(tc.path, scopes):
                kids.extend(self.nodes([tc], ctx, scopes))  # explicit override
                continue
            if sc is None:
                continue
            step = sc.name[:-2] if sc.name.endswith("[]") else sc.name
            found = self._step([loc], step)
            ttag = tc.name[:-2] if tc.name.endswith("[]") else tc.name
            if is_attribute(tc):
                if found:
                    kids.append(Out(ttag, text=_str(_text(found[0][0]))))
                continue
            repeats = tc.type == "array" or sc.type == "array"
            for cl in (found if repeats else found[:1]):
                if tc.children:
                    t, k = self.copy_struct(tc, cl, sc, ctx, scopes)
                    kids.append(Out(ttag, text=t, children=k))
                else:
                    kids.append(Out(ttag, text=_str(_text(cl[0]))))
        own = None
        if tgt.children and not has_element_children(tgt) and tgt.type not in ("object", "array"):
            own = _str(_text(loc[0]))
        return own, kids

    def run(self) -> list[Out]:
        for v in self.ws.variables:
            if v.name:
                self.assign(v.name, v.var_type, v.transform, v.inputs, [])
        rc = self.ws.root_condition
        if rc.transform.strip():
            node = parse_expr(rc.transform)
            cond = node.args[0] if node.type == "call" and node.func == "IF" and node.args else node
            if not _truthy(self.evaluate(cond, rc.inputs, [])):
                return []
        return self.nodes(self.ws.target.fields, [], [])


def _cast(v: Any, var_type: str) -> Any:
    """A variable's value converted to its data type."""
    import math
    if var_type == "boolean":
        return _truthy(v) if not isinstance(v, str) else v.strip().lower() in ("true", "1")
    if var_type in ("integer", "number"):
        try:
            f = float(str(v).replace(",", ".")) if v not in (None, "") else None
        except ValueError:
            return None
        if f is None or math.isnan(f):
            return None
        return int(f) if var_type == "integer" else f
    if var_type == "date":
        return (_str(v) or "")[:10]
    return _str(v) or ""


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ------------------------------------------------------------- engines
def run_processor(ws: MappingWorkspace, sample_inputs: dict[str, str], output_format: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    docs: dict[str, Any] = {}
    for s in ws.sources:
        text = (sample_inputs.get(s.id) or "").strip()
        if not text:
            warnings.append(f"No sample for {s.label} — its fields evaluate as empty.")
            continue
        docs[s.id] = _load_source(s.type, text, s.csv_header_row, s.fields)
    outs = Evaluator(ws, docs).run()
    if ws.target.type in ("swift", "fixed"):
        # Same shape as the generated XSLT: <SwiftMessage> / <Record>, written as text unless XML is chosen.
        from app.services.xslt_gen import text_output
        mt = swift_mt.tree_message_type(ws.target.fields) if ws.target.type == "swift" else ""
        wrapper = swift_mt.WRAPPER if ws.target.type == "swift" else fixed_width.WRAPPER
        attr = f' type="MT{mt}"' if mt else ""
        body = _xml(outs, 1, None) if outs else ""
        xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<{wrapper}{attr}>\n{body}\n</{wrapper}>'
        if not text_output(ws):
            return xml, warnings
        if ws.target.type == "swift":
            return swift_mt.write_mt(xml, mt), warnings
        return fixed_width.write_record(xml, ws.target.fields), warnings
    if output_format == "xml":
        body = _xml(outs, 0, ws.target.namespace) if outs else "<!-- empty result -->"
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body, warnings
    arrays = {(n.name[:-2]) for n in _flatten(ws.target.fields) if n.name.endswith("[]")}
    return json.dumps(_json(outs, arrays), indent=2), warnings


def run_xslt(xslt_text: str, ws: MappingWorkspace, sample_inputs: dict[str, str]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not ws.sources:
        raise TestRunError("No sources defined.")
    first = ws.sources[0]
    sample = (sample_inputs.get(first.id) or "").strip()
    if not sample:
        raise TestRunError(f"Paste a sample XML for {first.label} — the XSLT runs against it.")
    if not sample.startswith("<"):
        raise TestRunError(f"The XSLT engine needs XML input; {first.label}'s sample isn't XML. "
                           "Use the Processor engine for JSON/CSV/SWIFT sources.")
    if len(ws.sources) > 1:
        warnings.append("XSLT engine runs against Source 1 only; other sources are $sourceN params (empty here).")
    if ws.project.xslt_version == "1.0":
        # An XSLT 1.0 processor, so the test shows what a 1.0 runtime really produces.
        return _run_lxml(xslt_text, sample, warnings), warnings
    try:
        return _run_saxon(xslt_text, sample), warnings
    except ImportError as exc:
        raise TestRunError("XSLT 2.0 needs Saxon on the backend: pip install saxonche "
                           "(or switch the XSLT version to 1.0).") from exc


def _run_saxon(xslt_text: str, sample: str) -> str:
    """Saxon-HE (XSLT 3.0 processor; 1.0 stylesheets run in backwards-compatible mode)."""
    from saxonche import PySaxonApiError, PySaxonProcessor

    with PySaxonProcessor(license=False) as proc:
        xslt = proc.new_xslt30_processor()
        try:
            exe = xslt.compile_stylesheet(stylesheet_text=xslt_text)
        except PySaxonApiError as exc:
            raise TestRunError(f"Generated XSLT does not compile: {exc}") from exc
        try:
            doc = proc.parse_xml(xml_text=sample)
        except PySaxonApiError as exc:
            raise TestRunError(f"Sample is not valid XML: {exc}") from exc
        try:
            out = exe.transform_to_string(xdm_node=doc)
        except PySaxonApiError as exc:
            raise TestRunError(f"XSLT failed at runtime: {exc}") from exc
    if not out or not out.strip():
        return "<!-- XSLT produced no output -->"
    # Saxon writes the declaration on the same line as the root; keep it readable.
    return re.sub(r"^(<\?xml[^>]*\?>)\s*", r"\1\n", out)


def _run_lxml(xslt_text: str, sample: str, warnings: list[str]) -> str:
    try:
        from lxml import etree
    except ImportError as exc:
        raise TestRunError("No XSLT processor on the backend: pip install -r requirements.txt") from exc
    try:
        transform = etree.XSLT(etree.fromstring(xslt_text.encode("utf-8")))
    except etree.XSLTParseError as exc:
        raise TestRunError(f"Generated XSLT does not compile: {exc}") from exc
    except etree.XMLSyntaxError as exc:
        raise TestRunError(f"Generated XSLT is not well-formed: {exc}") from exc
    try:
        doc = etree.fromstring(sample.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        raise TestRunError(f"Sample is not valid XML: {exc}") from exc
    try:
        result = transform(doc)
    except etree.XSLTApplyError as exc:
        raise TestRunError(f"XSLT failed at runtime: {exc}") from exc
    for entry in transform.error_log:
        warnings.append(str(entry.message))
    if result.getroot() is None:  # text output (SWIFT MT) has no root element
        text = str(result)
        return text if text.strip() else "<!-- XSLT produced no output -->"
    return str(result)


def _flatten(nodes: list[FieldNode]) -> list[FieldNode]:
    out: list[FieldNode] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.children))
    return out

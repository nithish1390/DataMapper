"""
Shared model of the statement-based mapping tree, used identically by the XSLT
generator, the Test/Run evaluator and the link/lines builder:

- statements (for-each / if / choose) wrapped around any target node;
- choose branches open a *scope* ("<statementId>:<branchId>"), so each
  [When] / [Otherwise] carries its own copy of the element with its own
  mappings. Lookups walk the active scope chain innermost-first, then "";
- formulas reference source data by path — absolute ($s1/Doc/..., /Doc/...)
  or relative to the innermost for-each item (Name/FullName, ../X, .).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from app.models.schemas import FieldNode, MappingRule, MappingWorkspace, SourceRef, Statement
from app.services.transform_dsl import ExprNode, collect_refs, parse_expr


def segments(path: str) -> list[str]:
    """'Document.PmtInf[].PmtInfId' -> ['Document', 'PmtInf', 'PmtInfId']."""
    return [s[:-2] if s.endswith("[]") else s for s in path.split(".") if s]


@dataclass(frozen=True)
class LoopCtx:
    """One active for-each: iterating source `source_id` at absolute `path` (names, dot-joined)."""

    source_id: str
    path: str


GuardItem = Union[SourceRef, ExprNode]
LOOP_KINDS = ("for-each", "for-each-group")


def relative_to_context(ref: SourceRef, ctx: list[LoopCtx]) -> tuple[Optional[LoopCtx], list[str]]:
    """For a legacy input chip: the innermost for-each it lives under and the
    remaining segments relative to that loop's item; (None, absolute) otherwise."""
    ref_segs = segments(ref.path)
    for loop in reversed(ctx):
        if loop.source_id != ref.source_id:
            continue
        loop_segs = segments(loop.path)
        if ref_segs[:len(loop_segs)] == loop_segs:
            return loop, ref_segs[len(loop_segs):]
    return None, ref_segs


def is_attribute(node: FieldNode) -> bool:
    return node.name.startswith("@")


def has_element_children(node: FieldNode) -> bool:
    """True for real containers; an element whose only children are attributes holds a value."""
    return any(not is_attribute(c) for c in node.children)


def bare_name(n: FieldNode) -> str:
    return n.name[:-2] if n.name.endswith("[]") else n.name


def copy_pairs(tgt: FieldNode, src: FieldNode) -> tuple[list[tuple[FieldNode, Optional[FieldNode], bool]], list[FieldNode]]:
    """Copy-Of follows the *target* schema: each target child is filled from the source child
    with the same name; when none exists, a unique source child whose name is a prefix of it (or
    vice versa) is used — e.g. pain.001.001.03 BIC -> .06 BICFI. Returns ([(target child, source
    child or None, fuzzy)], source children that nothing uses)."""
    by_name = {bare_name(c): c for c in src.children}
    pairs: list[tuple[FieldNode, Optional[FieldNode], bool]] = []
    used: set[str] = set()
    for tc in tgt.children:
        sc = by_name.get(bare_name(tc))
        if sc is not None:
            used.add(bare_name(sc))
        pairs.append((tc, sc, False))
    spare = [c for c in src.children if bare_name(c) not in used]

    def kind(n: FieldNode) -> str:
        return "attr" if is_attribute(n) else ("group" if has_element_children(n) else "value")

    for i, (tc, sc, _f) in enumerate(pairs):
        if sc is not None:
            continue
        t = bare_name(tc).lstrip("@").lower()
        cands = [c for c in spare if kind(c) == kind(tc) and min(len(t), len(bare_name(c).lstrip("@"))) >= 3
                 and (t.startswith(bare_name(c).lstrip("@").lower()) or bare_name(c).lstrip("@").lower().startswith(t))]
        if len(cands) == 1:
            pairs[i] = (tc, cands[0], True)
            spare.remove(cands[0])
    return pairs, spare


def branch_key(st: Statement, i: int) -> str:
    return f"{st.id}:{st.whens[i].id or f'w{i}'}"


def otherwise_key(st: Statement) -> str:
    return f"{st.id}:o"


class Structure:
    def __init__(self, ws: MappingWorkspace):
        self.ws = ws
        self.source_ids = [s.id for s in ws.sources]
        self.maps: dict[tuple[str, str], MappingRule] = {(m.target, m.scope): m for m in ws.mappings}
        self.structs: dict[tuple[str, str], list[Statement]] = {
            (s.target, s.scope): list(s.statements) for s in ws.structures}
        # Legacy `for_each` flag on a mapping == a for-each statement over its first input.
        for m in ws.mappings:
            if m.for_each and m.inputs:
                stmts = self.structs.setdefault((m.target, m.scope), [])
                if not any(s.kind == "for-each" for s in stmts):
                    stmts.insert(0, Statement(id=f"legacy-{m.id}", kind="for-each", inputs=[m.inputs[0]]))
        self.mandatory = ws.target.mandatory_overrides
        self.choice_sel = ws.target.choice_selections
        # every variable name ($name): global ones and the ones declared in the target tree
        self.var_names: set[str] = {v.name for v in ws.variables} | {
            st.name for sts in self.structs.values() for st in sts if st.kind == "variable" and st.name}
        # node variables that hold an absolute source path: usable as a for-each select / path base
        self.var_paths: dict[str, tuple[str, list[str]]] = {}
        decls = [(v.name, v.var_type, v.transform) for v in ws.variables] + [
            (st.name, st.var_type, st.select) for sts in self.structs.values() for st in sts if st.kind == "variable"]
        for name, vtype, text in decls:
            node = parse_expr(text) if vtype == "node" and text else None
            if node is not None and node.type == "ref" and node.absolute and node.source_id in self.source_ids:
                self.var_paths[name] = self.resolve_abs(node, [])
        self._content: set[str] = set()
        for path, _ in list(self.maps) + list(self.structs):
            parts = path.split(".")
            for i in range(1, len(parts) + 1):
                self._content.add(".".join(parts[:i]))

    # ------------------------------------------------------------ lookups
    def mapping_for(self, path: str, scopes: list[str]) -> Optional[MappingRule]:
        for sc in [*reversed(scopes), ""]:
            m = self.maps.get((path, sc))
            if m:
                return m
        return None

    def stmts(self, path: str, scopes: list[str]) -> list[Statement]:
        for sc in [*reversed(scopes), ""]:
            st = self.structs.get((path, sc))
            if st:
                return st
        return []

    def excluded(self, node: FieldNode) -> bool:
        """An xs:choice alternative the user did not pick."""
        sel = self.choice_sel.get(node.choice or "")
        return bool(sel) and sel != node.path

    def is_mandatory(self, node: FieldNode) -> bool:
        if node.choice and self.choice_sel.get(node.choice) == node.path:
            return True
        return self.mandatory.get(node.path, node.mandatory)

    def has_content(self, node: FieldNode) -> bool:
        return node.path in self._content and not self.excluded(node)

    # ----------------------------------------------------------- formulas
    def is_copy(self, m: Optional[MappingRule], node: FieldNode) -> bool:
        """Copy-Of, explicitly — or implicitly: a plain path mapped onto an element
        that has children (value-of of a whole element isn't meaningful)."""
        if m is None:
            return False
        if m.mode == "copy-of":
            return True
        return has_element_children(node) and self.mapping_expr(m).type in ("ref", "placeholder")

    @staticmethod
    def mapping_expr(m: MappingRule) -> ExprNode:
        return parse_expr(m.transform if m.transform.strip() else ("{0}" if m.inputs else "''"))

    @staticmethod
    def select_expr(st: Statement) -> Optional[ExprNode]:
        if st.select.strip():
            return parse_expr(st.select)
        if st.inputs:
            return ExprNode(type="placeholder", index=0)
        return None

    def first_source(self) -> str:
        return self.source_ids[0] if self.source_ids else ""

    def resolve_abs(self, ref: ExprNode, ctx: list[LoopCtx]) -> tuple[str, list[str]]:
        """Absolute (source_id, name segments) a path reference points at
        (current-group()/X resolves like a path relative to the grouped items)."""
        if ref.absolute and ref.source_id not in self.source_ids and ref.source_id in getattr(self, "var_paths", {}):
            sid, base = self.var_paths[ref.source_id][0], list(self.var_paths[ref.source_id][1])  # $payments/X
        elif ref.absolute:
            sid = ref.source_id if ref.source_id in self.source_ids else self.first_source()
            base = []
        elif ctx:
            sid, base = ctx[-1].source_id, segments(ctx[-1].path)
        else:
            sid, base = self.first_source(), []
        segs = list(base)
        for step in ref.steps:
            if step == ".":
                continue
            if step == "..":
                if segs:
                    segs.pop()
                continue
            segs.append(step)
        return sid, segs

    def loop_for(self, st: Statement, ctx: list[LoopCtx]) -> Optional[LoopCtx]:
        node = self.select_expr(st)
        if node is None:
            return None
        if node.type == "placeholder" and st.inputs:
            return LoopCtx(st.inputs[0].source_id, ".".join(segments(st.inputs[0].path)))
        if node.type == "var" and node.name in self.var_paths:  # for-each over a node variable
            sid, segs = self.var_paths[node.name]
            return LoopCtx(sid, ".".join(segs))
        refs = collect_refs(node)
        if not refs:
            return None
        sid, segs = self.resolve_abs(refs[0], ctx)
        return LoopCtx(sid, ".".join(segs))

    def source_node(self, source_id: str, segs: list[str]) -> Optional[FieldNode]:
        src = next((s for s in self.ws.sources if s.id == source_id), None)
        if not src or not segs:
            return None
        nodes, found = src.fields, None
        for seg in segs:
            found = next((n for n in nodes if (n.name[:-2] if n.name.endswith("[]") else n.name) == seg), None)
            if found is None:
                return None
            nodes = found.children
        return found

    def copy_source(self, m: MappingRule, ctx: list[LoopCtx]) -> Optional[tuple[str, FieldNode]]:
        """(source id, source node) a Copy-Of mapping copies from."""
        expr = self.mapping_expr(m)
        if expr.type == "placeholder" and expr.index < len(m.inputs):
            inp = m.inputs[expr.index]
            node = self.source_node(inp.source_id, segments(inp.path))
            return (inp.source_id, node) if node else None
        refs = collect_refs(expr)
        if not refs:
            return None
        sid, segs = self.resolve_abs(refs[0], ctx)
        node = self.source_node(sid, segs)
        return (sid, node) if node else None

    def tree_path(self, source_id: str, segs: list[str]) -> Optional[str]:
        """Source-tree path (with [] markers) for name segments, or None."""
        src = next((s for s in self.ws.sources if s.id == source_id), None)
        if not src or not segs:
            return None
        nodes, found = src.fields, None
        for seg in segs:
            found = next((n for n in nodes if (n.name[:-2] if n.name.endswith("[]") else n.name) == seg), None)
            if found is None:
                return None
            nodes = found.children
        return found.path if found else None

    # -------------------------------------------------------------- guard
    def guard_items(self, node: FieldNode, scopes: list[str]) -> Optional[list[tuple[GuardItem, Optional[MappingRule]]]]:
        """For an optional container: every source path its descendants read
        (it is written only if one of them exists). None when something below
        emits unconditionally (constants, statements, copy-of), or when the
        container is mandatory."""
        if self.is_mandatory(node):
            return None
        items: list[tuple[GuardItem, Optional[MappingRule]]] = []

        def collect(n: FieldNode) -> bool:
            if self.excluded(n):
                return True
            stmts = self.stmts(n.path, scopes)
            if stmts:
                # A for-each first: the element only has content if the loop has items.
                st = stmts[0]
                sel = self.select_expr(st) if st.kind in LOOP_KINDS else None
                if sel is None:
                    return False
                if sel.type == "placeholder":
                    items.append((st.inputs[0], None))
                else:
                    items.extend((r, None) for r in collect_refs(sel))
                return True
            m = self.mapping_for(n.path, scopes)
            if m:
                if self.is_copy(m, n):
                    return False
                expr = self.mapping_expr(m)
                refs = collect_refs(expr)
                uses_inputs = [m.inputs[i] for i in sorted({x.index for x in _placeholders(expr)}) if i < len(m.inputs)]
                if not refs and not uses_inputs:
                    return False
                items.extend((r, m) for r in refs)
                items.extend((r, m) for r in uses_inputs)
            return all(collect(c) for c in n.children)

        return items if collect(node) and items else None

    def ancestors_ctx(self, target_path: str) -> tuple[Optional[FieldNode], list[LoopCtx]]:
        """The node for target_path and the for-each contexts its ancestors open."""

        def walk(nodes: list[FieldNode], ctx: list[LoopCtx]):
            for n in nodes:
                own = list(ctx)
                for st in self.stmts(n.path, []):
                    if st.kind in LOOP_KINDS:
                        loop = self.loop_for(st, own)
                        if loop:
                            own.append(loop)
                if n.path == target_path:
                    return n, ctx, own
                found = walk(n.children, own)
                if found:
                    return found
            return None

        found = walk(self.ws.target.fields, [])
        return (found[0], found[1]) if found else (None, [])

    def inner_ctx(self, target_path: str) -> list[LoopCtx]:
        """Contexts in effect *inside* target_path (its own for-each included)."""
        node, ctx = self.ancestors_ctx(target_path)
        if node is None:
            return []
        own = list(ctx)
        for st in self.stmts(node.path, []):
            if st.kind in LOOP_KINDS:
                loop = self.loop_for(st, own)
                if loop:
                    own.append(loop)
        return own


def _placeholders(node: ExprNode) -> list[ExprNode]:
    from app.services.transform_dsl import walk
    return [n for n in walk(node) if n.type == "placeholder"]

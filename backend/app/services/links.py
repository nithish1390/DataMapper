"""
Source -> target links for the mapping lines in the UI. Walks the target
tree exactly like the XSLT writer (statements, branch scopes, for-each
context), resolves every path a formula reads to a source-tree path, and
tags it with the UI row it belongs to.

Row keys (the UI builds the same strings):
  element   e|<target path>|<innermost scope or "">
  for-each / if   s|<statement id>
  when      w|<statement id>|<branch scope key>
"""
from __future__ import annotations

import re

from app.models.schemas import FieldNode, MappingLink, MappingWorkspace, RowProblem, SourceRef, Statement
from app.services.structure import LoopCtx, Structure, bare_name, branch_key, copy_pairs, otherwise_key
from app.services.transform_dsl import ExprNode, collect_refs, needs_xpath2, parse_expr, walk


class _Links:
    def __init__(self, ws: MappingWorkspace):
        self.s = Structure(ws)
        self.out: list[MappingLink] = []
        self.problems: list[RowProblem] = []
        self.seen: set[tuple] = set()
        self.copied_paths: set[str] = set()  # target paths filled by an ancestor's Copy-Of
        self.v1 = ws.project.xslt_version == "1.0"

    def problem(self, row_key: str, target: str, message: str) -> None:
        self.problems.append(RowProblem(row_key=row_key, target=target, message=message))

    def add_expr(self, expr: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx],
                 target: str, scope: str, row_key: str, kind: str) -> None:
        if expr.error:
            self.problem(row_key, target, f"Formula error: {expr.error}")
        if self.v1:
            need = needs_xpath2(expr)
            if need:
                self.problem(row_key, target, f"{', '.join(dict.fromkeys(need))} needs XSLT 2.0 — "
                             "switch the XSLT version to 2.0, or use a 1.0 alternative")
        bad_ph = [n.index for n in walk(expr) if n.type == "placeholder" and n.index >= len(inputs)]
        if bad_ph:
            self.problem(row_key, target, f"{{{bad_ph[0]}}} has no source input")
        refs: list[tuple[str, str]] = []
        for r in collect_refs(expr):
            if r.absolute and r.source_id not in self.s.source_ids and r.source_id in self.s.var_names \
                    and r.source_id not in self.s.var_paths:
                continue  # a path into a node variable whose source path isn't known statically
            sid, segs = self.s.resolve_abs(r, ctx)
            if r.steps and not segs:
                self.problem(row_key, target, f"'{'/'.join(r.steps)}' points above the document root")
                continue
            if segs and not self.s.tree_path(sid, segs):
                shown = ("$" + sid + "/" if r.absolute else "") + "/".join(r.steps)
                self.problem(row_key, target, f"Source path '{shown}' does not exist in {sid}")
            while segs:
                path = self.s.tree_path(sid, segs)
                if path:
                    refs.append((sid, path))
                    break
                segs = segs[:-1]
        refs.extend((i.source_id, i.path) for i in inputs)
        for sid, path in refs:
            key = (sid, path, row_key)
            if key in self.seen:
                continue
            self.seen.add(key)
            self.out.append(MappingLink(source_id=sid, source_path=path, target=target, scope=scope,
                                        row_key=row_key, kind=kind))

    def copy_source(self, m, ctx: list[LoopCtx]):
        return self.s.copy_source(m, ctx)

    def copied(self, sid: str, src: FieldNode, tgt: FieldNode, scope: str,
               ctx: list[LoopCtx] = (), scopes: list[str] = ()) -> None:
        """Copy-Of: link each target sub-field to the source sub-field it is filled from;
        explicitly mapped sub-fields are walked like normal mappings (they override the copy)."""
        ctx, scopes = list(ctx), list(scopes)
        pairs, spare = copy_pairs(tgt, src)
        for tc, sc, fuzzy in pairs:
            key = f"e|{tc.path}|{scope}"
            if self.s.excluded(tc):
                continue
            if self.s.mapping_for(tc.path, scopes) or self.s.stmts(tc.path, scopes):
                self.copied_paths.add(tc.path)
                self.wrap(tc, self.s.stmts(tc.path, scopes), ctx, scopes)
                continue
            if sc is None:
                if self.s.is_mandatory(tc):
                    self.problem(key, tc.path, f"Copy-Of source has no '{bare_name(tc)}' (mandatory here) — map it explicitly")
                continue
            self.copied_paths.add(tc.path)
            self.out.append(MappingLink(source_id=sid, source_path=sc.path, target=tc.path, scope=scope,
                                        row_key=key, kind="copy-of"))
            self.copied(sid, sc, tc, scope, ctx, scopes)
        if spare:
            self.problem(f"e|{tgt.path}|{scope}", tgt.path,
                         f"Not copied (the target has no such element): {', '.join(bare_name(c) for c in spare[:6])}"
                         " — map them explicitly if needed")

    def nodes(self, nodes: list[FieldNode], ctx: list[LoopCtx], scopes: list[str]) -> None:
        for n in nodes:
            if self.s.excluded(n) and n.path in self.s._content:
                self.problem(f"e|{n.path}|{scopes[-1] if scopes else ''}", n.path,
                             "Mapped, but this choice option is not the selected one — it will not be written")
            if self.s.has_content(n):
                self.wrap(n, self.s.stmts(n.path, scopes), ctx, scopes)

    def wrap(self, n: FieldNode, stmts: list[Statement], ctx: list[LoopCtx], scopes: list[str]) -> None:
        scope = scopes[-1] if scopes else ""
        if not stmts:
            m = self.s.mapping_for(n.path, scopes)
            if m and self.s.is_copy(m, n) and not m.inputs and not collect_refs(self.s.mapping_expr(m)):
                self.problem(f"e|{n.path}|{scope}", n.path, "Copy-Of needs a source element")
            if m:
                self.add_expr(self.s.mapping_expr(m), m.inputs, ctx, n.path, scope, f"e|{n.path}|{scope}",
                              "copy-of" if self.s.is_copy(m, n) else "value-of")
            if self.s.is_copy(m, n):
                src = self.copy_source(m, ctx)
                if src:
                    self.copied(src[0], src[1], n, scope, ctx, scopes)
                return
            self.nodes(n.children, ctx, scopes)
            return
        st, rest = stmts[0], stmts[1:]
        if st.kind == "variable":
            key = f"s|{st.id}"
            if not re.fullmatch(r"[A-Za-z_][\w.-]*", st.name or ""):
                self.problem(key, n.path, "Variable needs a valid name (letters, digits, _ ; not starting with a digit)")
            elif st.name in self.s.source_ids:
                self.problem(key, n.path, f"Variable name '{st.name}' clashes with the source id ${st.name}")
            if not st.select.strip():
                self.problem(key, n.path, f"Variable ${st.name or '?'} has no formula")
            else:
                self.add_expr(parse_expr(st.select), st.inputs, ctx, n.path, scope, key, "value-of")
            self.wrap(n, rest, ctx, scopes)
            return
        if st.kind == "for-each-group":
            sel = self.s.select_expr(st)
            if sel is not None:
                self.add_expr(sel, st.inputs, ctx, n.path, scope, f"s|{st.id}", "for-each")
            else:
                self.problem(f"s|{st.id}", n.path, "For-Each-Group needs a repeating source (select)")
            if self.v1:
                self.problem(f"s|{st.id}", n.path, "For-Each-Group needs XSLT 2.0 (in 1.0 it is written as a plain For-Each)")
            loop = self.s.loop_for(st, ctx)
            inner = ctx + [loop] if loop else ctx
            if not st.group_by.strip():
                self.problem(f"s|{st.id}", n.path, "For-Each-Group needs a group-by key")
            else:
                self.add_expr(parse_expr(st.group_by), [], inner, n.path, scope, f"s|{st.id}", "if")
            self.wrap(n, rest, inner, scopes)
            return
        if st.kind == "for-each":
            sel = self.s.select_expr(st)
            if sel is not None:
                self.add_expr(sel, st.inputs, ctx, n.path, scope, f"s|{st.id}", "for-each")
            else:
                self.problem(f"s|{st.id}", n.path, "For-Each needs a repeating source (select)")
            loop = self.s.loop_for(st, ctx)
            self.wrap(n, rest, ctx + [loop] if loop else ctx, scopes)
        elif st.kind == "if":
            if not st.test.strip() and not st.inputs:
                self.problem(f"s|{st.id}", n.path, "[If] needs a test")
            self.add_expr(parse_expr(st.test), st.inputs, ctx, n.path, scope, f"s|{st.id}", "if")
            self.wrap(n, rest, ctx, scopes)
        else:
            for i, w in enumerate(st.whens):
                key = branch_key(st, i)
                if not w.test.strip() and not st.inputs:
                    self.problem(f"w|{st.id}|{key}", n.path, "[When] needs a test")
                self.add_expr(parse_expr(w.test), st.inputs, ctx, n.path, scope, f"w|{st.id}|{key}", "when")
                self.wrap(n, rest, ctx, scopes + [key])
            if st.otherwise is not None:
                self.wrap(n, rest, ctx, scopes + [otherwise_key(st)])


def collect_links(ws: MappingWorkspace) -> list[MappingLink]:
    w = _Links(ws)
    w.nodes(ws.target.fields, [], [])
    return w.out


def analyse(ws: MappingWorkspace) -> tuple[list[MappingLink], list[RowProblem]]:
    w = walk_mapping(ws)
    return w.out, w.problems


def walk_mapping(ws: MappingWorkspace) -> "_Links":
    w = _Links(ws)
    names: dict[str, int] = {}
    for v in ws.variables:  # global variables: rows "v|<id>" at the top of the target tree
        key = f"v|{v.id}"
        names[v.name] = names.get(v.name, 0) + 1
        if not re.fullmatch(r"[A-Za-z_][\w.-]*", v.name or ""):
            w.problem(key, "", "Variable needs a valid name (letters, digits, _ ; not starting with a digit)")
        elif v.name in w.s.source_ids:
            w.problem(key, "", f"Variable name '{v.name}' clashes with the source id ${v.name}")
        if v.transform.strip() or v.inputs:
            w.add_expr(parse_expr(v.transform or "{0}"), v.inputs, [], "", "", key, "value-of")
    for name, count in names.items():
        if count > 1:
            for v in ws.variables:
                if v.name == name:
                    w.problem(f"v|{v.id}", "", f"Variable name ${name} is used {count} times")
    w.nodes(ws.target.fields, [], [])
    return w

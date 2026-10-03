"""
XSLT generation (1.0 or 2.0) for the statement-based mapping tree.

Walks the target tree; every target node (root element, container or leaf)
can carry a stack of statements — for-each, if, choose/when/otherwise —
nested in any order. Each choose branch carries its own copy of the element
(branch-scoped mappings). Formulas are XPath-flavoured: relative paths
resolve against the innermost for-each item, absolute ones ($s1/..., /...)
against the source document. XSD namespaces become s1:, s2: ... prefixes so
the stylesheet matches namespaced input.
"""
from __future__ import annotations

from typing import Optional

from app.models.schemas import FieldNode, MappingWorkspace, SourceRef, Statement
from app.services.structure import (
    LoopCtx, Structure, branch_key, copy_pairs, has_element_children, is_attribute, otherwise_key,
    relative_to_context,
)
from app.services.transform_dsl import KNOWN_FUNCS, XPATH2_FUNCS, ExprNode, collect_refs, expr_to_xpath, parse_expr, uses_func

XSL_NS = "http://www.w3.org/1999/XSL/Transform"
XS_NS = "http://www.w3.org/2001/XMLSchema"
EXSLT_DATE_NS = "http://exslt.org/dates-and-times"


def _attr(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _tag(node: FieldNode) -> str:
    return node.name[:-2] if node.name.endswith("[]") else node.name


class XsltWriter:
    def __init__(self, ws: MappingWorkspace):
        self.ws = ws
        self.s = Structure(ws)
        self.src_index = {src.id: i for i, src in enumerate(ws.sources)}
        self.version = ws.project.xslt_version
        self.v2 = self.version.startswith("2")
        self.uses_date = False      # XPath 2.0 date functions (xs: namespace)
        self.uses_exslt = False     # XSLT 1.0: EXSLT date:date-time()
        self.uses_copy_ns = False

    # ------------------------------------------------------------- paths
    def _prefix(self, source_id: str) -> Optional[str]:
        i = self.src_index.get(source_id, 0)
        return f"s{i + 1}" if i < len(self.ws.sources) and self.ws.sources[i].namespace else None

    def _steps(self, steps: list[str], source_id: str) -> str:
        prefix = self._prefix(source_id)

        def step(seg: str) -> str:
            if seg in (".", "..") or seg.startswith("@") or not prefix:
                return seg
            return f"{prefix}:{seg}"

        return "/".join(step(s) for s in steps)

    def _absolute(self, source_id: str, segs: list[str]) -> str:
        i = self.src_index.get(source_id, 0)
        body = self._steps(segs, source_id)
        return f"/{body}" if i == 0 else f"$source{i + 1}/{body}"

    def xpath(self, ref: SourceRef, ctx: list[LoopCtx]) -> str:
        """Legacy input chip -> XPath (relative inside a matching for-each)."""
        loop, rel = relative_to_context(ref, ctx)
        if loop is not None:
            return self._steps(rel, ref.source_id) if rel else "."
        return self._absolute(ref.source_id, rel)

    def ref_xpath(self, ref: ExprNode, ctx: list[LoopCtx]) -> str:
        if ref.group:
            sid = ctx[-1].source_id if ctx else self.s.first_source()
            return "current-group()" + ("/" + self._steps(ref.steps, sid) if ref.steps else "")
        if ref.absolute:
            sid = ref.source_id if ref.source_id in self.src_index else self.s.first_source()
            return self._absolute(sid, ref.steps)
        sid = ctx[-1].source_id if ctx else self.s.first_source()
        return self._steps(ref.steps, sid) or "."

    def xp(self, node: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx], single: bool = False):
        """single=True where one value is expected (value-of, tests, function arguments)."""
        out = expr_to_xpath(node, [self.xpath(i, ctx) for i in inputs], lambda r: self.ref_xpath(r, ctx),
                            version=self.version, single=single)
        if isinstance(out, str):
            self.uses_date |= self.v2 and "xs:" in out
            self.uses_exslt |= not self.v2 and "date:" in out
        return out

    # ------------------------------------------------------- expressions
    def cond(self, text: str, inputs: list[SourceRef], ctx: list[LoopCtx]) -> str:
        if not text.strip():
            return self.xpath(inputs[0], ctx) if inputs else "true()"
        out = self.xp(parse_expr(text), inputs, ctx, single=True)
        return out if isinstance(out, str) else "false()"

    def value(self, node: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx]) -> str:
        """Inline XSLT producing the value of a formula."""
        if node.type == "call" and node.func in ("IF", "WHEN"):
            parts = node.args
            if node.func == "IF":
                parts = parts + ([parse_expr("''")] if len(parts) < 3 else [])
            n = len(parts)
            out = "<xsl:choose>"
            i = 0
            while i + 1 < n - (1 if n % 2 == 1 else 0):
                c = self.xp(parts[i], inputs, ctx, single=True)
                out += (f'<xsl:when test="{_attr(c if isinstance(c, str) else "false()")}">'
                        f"{self.value(parts[i + 1], inputs, ctx)}</xsl:when>")
                i += 2
            if n % 2 == 1:
                out += f"<xsl:otherwise>{self.value(parts[-1], inputs, ctx)}</xsl:otherwise>"
            return out + "</xsl:choose>"
        sel = self.xp(node, inputs, ctx, single=True)
        prefix = ""
        if node.error:
            prefix = f"<!-- formula error: {node.error.replace('--', '-')} -->"
        elif node.type == "call" and node.func not in KNOWN_FUNCS and ":" not in node.func_raw:
            prefix = f"<!-- TODO custom function {node.func_raw}(): not available in XSLT 1.0 -->"
        return f'{prefix}<xsl:value-of select="{_attr(sel if isinstance(sel, str) else "")}"/>'

    # ------------------------------------------------------------- nodes
    def nodes(self, nodes: list[FieldNode], ctx: list[LoopCtx], scopes: list[str], depth: int) -> list[str]:
        out: list[str] = []
        for n in nodes:
            if self.s.has_content(n):
                out.extend(self.node(n, ctx, scopes, depth))
        return out

    def node(self, n: FieldNode, ctx: list[LoopCtx], scopes: list[str], depth: int) -> list[str]:
        return self.wrap(n, self.s.stmts(n.path, scopes), ctx, scopes, depth, None)

    def wrap(self, n: FieldNode, stmts: list[Statement], ctx: list[LoopCtx], scopes: list[str], depth: int,
             override: Optional[tuple[Statement, str]]) -> list[str]:
        if not stmts:
            return self.element(n, ctx, scopes, depth, override)
        st, rest = stmts[0], stmts[1:]
        ind = "  " * depth
        if st.kind == "for-each":
            sel_node = self.s.select_expr(st)
            if sel_node is None:
                return [f"{ind}<!-- for-each on {_tag(n)}: no select yet -->",
                        *self.wrap(n, rest, ctx, scopes, depth, override)]
            sel = self.xp(sel_node, st.inputs, ctx)
            loop = self.s.loop_for(st, ctx)
            inner_ctx = ctx + [loop] if loop else ctx
            return [f'{ind}<xsl:for-each select="{_attr(sel if isinstance(sel, str) else "")}">',
                    *self.wrap(n, rest, inner_ctx, scopes, depth + 1, override),
                    f"{ind}</xsl:for-each>"]
        if st.kind == "for-each-group":
            sel_node = self.s.select_expr(st)
            if sel_node is None:
                return [f"{ind}<!-- for-each-group on {_tag(n)}: no select yet -->",
                        *self.wrap(n, rest, ctx, scopes, depth, override)]
            sel = self.xp(sel_node, st.inputs, ctx)
            loop = self.s.loop_for(st, ctx)
            inner_ctx = ctx + [loop] if loop else ctx
            key = self.xp(parse_expr(st.group_by or "."), [], inner_ctx, single=True)
            if not self.v2:  # no grouping in XSLT 1.0: plain loop (reported as a problem)
                return [f"{ind}<!-- for-each-group needs XSLT 2.0: written as for-each -->",
                        f'{ind}<xsl:for-each select="{_attr(sel if isinstance(sel, str) else "")}">',
                        *self.wrap(n, rest, inner_ctx, scopes, depth + 1, override), f"{ind}</xsl:for-each>"]
            return [f'{ind}<xsl:for-each-group select="{_attr(sel if isinstance(sel, str) else "")}" '
                    f'group-by="{_attr(key if isinstance(key, str) else ".")}">',
                    *self.wrap(n, rest, inner_ctx, scopes, depth + 1, override),
                    f"{ind}</xsl:for-each-group>"]
        if st.kind == "if":
            return [f'{ind}<xsl:if test="{_attr(self.cond(st.test, st.inputs, ctx))}">',
                    *self.wrap(n, rest, ctx, scopes, depth + 1, override),
                    f"{ind}</xsl:if>"]
        lines = [f"{ind}<xsl:choose>"]
        for i, w in enumerate(st.whens):
            branch = (st, w.value) if w.value.strip() else override
            lines += [f'{ind}  <xsl:when test="{_attr(self.cond(w.test, st.inputs, ctx))}">',
                      *self.wrap(n, rest, ctx, scopes + [branch_key(st, i)], depth + 2, branch),
                      f"{ind}  </xsl:when>"]
        if st.otherwise is not None:
            branch = (st, st.otherwise) if st.otherwise.strip() else override
            lines += [f"{ind}  <xsl:otherwise>",
                      *self.wrap(n, rest, ctx, scopes + [otherwise_key(st)], depth + 2, branch),
                      f"{ind}  </xsl:otherwise>"]
        lines.append(f"{ind}</xsl:choose>")
        return lines

    def _source_of(self, expr: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx]) -> Optional[str]:
        if expr.type == "placeholder" and expr.index < len(inputs):
            return inputs[expr.index].source_id
        refs = collect_refs(expr)
        return self.s.resolve_abs(refs[0], ctx)[0] if refs else None

    def needs_renamespace(self, source_id: Optional[str]) -> bool:
        i = self.src_index.get(source_id or "", 0)
        src_ns = self.ws.sources[i].namespace if i < len(self.ws.sources) else None
        return bool(src_ns) and src_ns != (self.ws.target.namespace or "")

    def element(self, n: FieldNode, ctx: list[LoopCtx], scopes: list[str], depth: int,
                override: Optional[tuple[Statement, str]]) -> list[str]:
        ind = "  " * depth
        tag = _tag(n)
        m = self.s.mapping_for(n.path, scopes)
        attr = is_attribute(n)

        def wrap_value(inner: str) -> str:
            return (f'{ind}<xsl:attribute name="{tag[1:]}">{inner}</xsl:attribute>' if attr
                    else f"{ind}<{tag}>{inner}</{tag}>")

        if override is not None and not has_element_children(n) and not n.children:
            st, expr = override
            return [wrap_value(self.value(parse_expr(expr), st.inputs, ctx))]

        if not attr and self.s.is_copy(m, n):
            expr = self.s.mapping_expr(m)
            src_node = self._copy_source_node(expr, m.inputs, ctx)
            sel = self.xp(expr, m.inputs, ctx)
            if src_node is not None and isinstance(sel, str):
                # Structure-aware copy: follow the target schema, overrides allowed underneath.
                prefix = self._prefix(self._source_of(expr, m.inputs, ctx) or self.s.first_source())
                return [f"{ind}<{tag}>", *self.copy_struct(n, sel, src_node, ctx, scopes, depth + 1, prefix),
                        f"{ind}</{tag}>"]
            sel = self.xp(expr, m.inputs, ctx)
            sel = sel if isinstance(sel, str) else "."
            # attributes first, then child nodes
            node_sel = "@*|node()" if sel == "." else f"{sel}/@*|{sel}/node()"
            if self.needs_renamespace(self._source_of(expr, m.inputs, ctx)):
                # Same structure, different namespace (e.g. pain.001.001.03 -> .06):
                # copy, but rebuild each element in the target namespace.
                self.uses_copy_ns = True
                return [f'{ind}<{tag}><xsl:apply-templates select="{_attr(node_sel)}" mode="copy-ns"/></{tag}>']
            return [f'{ind}<{tag}><xsl:copy-of select="{_attr(node_sel)}"/></{tag}>']

        if n.children:
            # attributes (listed first) + child elements + this element's own value (simple content)
            inner = self.nodes(n.children, ctx, scopes, depth + 1)
            if m:
                inner.append(f"{ind}  {self.value(self.s.mapping_expr(m), m.inputs, ctx)}")
            if not inner:
                return [f"{ind}<{tag}/>"] if self.s.stmts(n.path, scopes) else []
            lines = [f"{ind}<{tag}>", *inner, f"{ind}</{tag}>"]
            guard = self.exists_guard(n, ctx, scopes)
            if guard:
                # Optional element: only emit it when some source it maps from exists.
                return [f'{ind}<xsl:if test="{_attr(guard)}">', *["  " + l for l in lines], f"{ind}</xsl:if>"]
            return lines

        if not m:
            return []
        expr = self.s.mapping_expr(m)
        line = wrap_value(self.value(expr, m.inputs, ctx))
        if expr.type in ("ref", "placeholder") and not self.s.is_mandatory(n):
            # Optional target fed straight from a source path: only emit it when that exists.
            test = self.xp(expr, m.inputs, ctx)
            return [f'{ind}<xsl:if test="{_attr(test)}">', "  " + line, f"{ind}</xsl:if>"]
        return [line]

    def _copy_source_node(self, expr: ExprNode, inputs: list[SourceRef], ctx: list[LoopCtx]) -> Optional[FieldNode]:
        if expr.type == "placeholder" and expr.index < len(inputs):
            inp = inputs[expr.index]
            return self.s.source_node(inp.source_id, [x[:-2] if x.endswith("[]") else x for x in inp.path.split(".")])
        refs = collect_refs(expr)
        if not refs:
            return None
        sid, segs = self.s.resolve_abs(refs[0], ctx)
        return self.s.source_node(sid, segs)

    def copy_struct(self, tgt: FieldNode, sel: str, src: FieldNode, ctx: list[LoopCtx], scopes: list[str],
                    depth: int, prefix: Optional[str]) -> list[str]:
        """Children of a Copy-Of element, built along the target schema from `sel` (an XPath to the
        source element, valid in the current context). Explicitly mapped children override the copy.
        The XSLT context only changes inside repeating children (xsl:for-each)."""
        ind = "  " * depth
        out: list[str] = []
        pairs, _spare = copy_pairs(tgt, src)
        for tc, sc, _fuzzy in pairs:
            if self.s.excluded(tc):
                continue
            if self.s.mapping_for(tc.path, scopes) or self.s.stmts(tc.path, scopes):
                out.extend(self.node(tc, ctx, scopes, depth))  # explicit override
                continue
            if sc is None:
                continue
            step = sc.name[:-2] if sc.name.endswith("[]") else sc.name
            if not is_attribute(sc) and prefix:
                step = f"{prefix}:{step}"
            child = step if sel == "." else f"{sel}/{step}"
            ttag = _tag(tc)
            if is_attribute(tc):
                out += [f'{ind}<xsl:if test="{_attr(child)}">',
                        f'{ind}  <xsl:attribute name="{ttag[1:]}"><xsl:value-of select="{_attr(f"({child})[1]" if self.v2 else child)}"/></xsl:attribute>',
                        f"{ind}</xsl:if>"]
                continue
            repeats = tc.type == "array" or sc.type == "array"
            here = "." if repeats else child
            inner_depth = depth + 2
            one = f"({here})[1]" if self.v2 and here != "." else here
            body = self.copy_struct(tc, here, sc, ctx, scopes, inner_depth, prefix) if tc.children else \
                [f'{"  " * inner_depth}<xsl:value-of select="{_attr(one)}"/>']
            open_, close = (f'{ind}<xsl:for-each select="{_attr(child)}">', f"{ind}</xsl:for-each>") if repeats \
                else (f'{ind}<xsl:if test="{_attr(child)}">', f"{ind}</xsl:if>")
            out += [open_, f"{ind}  <{ttag}>", *body, f"{ind}  </{ttag}>", close]
        if tgt.children and not has_element_children(tgt) and tgt.type not in ("object", "array"):
            out.append(f'{ind}<xsl:value-of select="{_attr(sel)}"/>')  # value next to its attributes
        return out

    def exists_guard(self, n: FieldNode, ctx: list[LoopCtx], scopes: list[str]) -> Optional[str]:
        items = self.s.guard_items(n, scopes)
        if not items:
            return None
        paths = []
        for item, _m in items:
            paths.append(self.ref_xpath(item, ctx) if isinstance(item, ExprNode) else self.xpath(item, ctx))
        if any(p.startswith("$") or p in (".", "") or ".." in p for p in paths):
            return None
        return " | ".join(dict.fromkeys(paths))

    # ---------------------------------------------------------- document
    def variables(self) -> list[str]:
        out = []
        for v in self.ws.variables:
            node = parse_expr(v.transform if v.transform.strip() else ("{0}" if v.inputs else "''"))
            if node.type == "call" and node.func in ("IF", "WHEN"):
                out.append(f'  <xsl:variable name="{v.name}">{self.value(node, v.inputs, [])}</xsl:variable>')
            else:
                sel = self.xp(node, v.inputs, [])
                out.append(f'  <xsl:variable name="{v.name}" select="{_attr(sel if isinstance(sel, str) else "")}"/>')
        return out

    def body(self) -> list[str]:
        ws = self.ws
        if ws.target.type == "xsd" or any(n.children for n in ws.target.fields):
            inner = self.nodes(ws.target.fields, [], [], 2)
        else:
            inner = ["    <target>", *self.nodes(ws.target.fields, [], [], 3), "    </target>"]
        if not inner:
            inner = ["    <!-- no mappings defined yet -->"]
        rc = ws.root_condition
        if rc.transform.strip() and (rc.inputs or collect_refs(parse_expr(rc.transform))):
            node = parse_expr(rc.transform)
            test = node.args[0] if node.type == "call" and node.func == "IF" else node
            cond = self.xp(test, rc.inputs, [])
            inner = [f'    <xsl:if test="{_attr(cond if isinstance(cond, str) else "true()")}">',
                     *["  " + l for l in inner], "    </xsl:if>"]
        return inner

    def copy_ns_template(self) -> list[str]:
        ns = self.ws.target.namespace or ""
        return [
            "",
            "  <!-- copy-of into the target namespace -->",
            '  <xsl:template match="*" mode="copy-ns">',
            f'    <xsl:element name="{{local-name()}}" namespace="{ns}">',
            '      <xsl:copy-of select="@*"/>',
            '      <xsl:apply-templates select="node()" mode="copy-ns"/>',
            "    </xsl:element>",
            "  </xsl:template>",
            '  <xsl:template match="@*|text()|comment()" mode="copy-ns"><xsl:copy/></xsl:template>',
        ]

    def stylesheet(self) -> str:
        ws = self.ws
        variables = self.variables()
        body = self.body()
        ns_decls = [f'xmlns:xsl="{XSL_NS}"']
        excluded = []
        for i, src in enumerate(ws.sources):
            if src.namespace:
                ns_decls.append(f'xmlns:s{i + 1}="{src.namespace}"')
                excluded.append(f"s{i + 1}")
        if self.v2:
            ns_decls.append(f'xmlns:xs="{XS_NS}"')
            excluded.append("xs")
        if self.uses_exslt:
            ns_decls.append(f'xmlns:date="{EXSLT_DATE_NS}"')
            excluded.append("date")
        if ws.target.namespace:
            ns_decls.append(f'xmlns="{ws.target.namespace}"')
        exclude = f' exclude-result-prefixes="{" ".join(excluded)}"' if excluded else ""
        params = [f'  <xsl:param name="source{i + 1}" select="/.."/>  <!-- {s.label}: pass as a node-set -->'
                  for i, s in enumerate(ws.sources) if i > 0]
        n_stmts = sum(len(s.statements) for s in ws.structures)
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<xsl:stylesheet version="{self.version}" {" ".join(ns_decls)}{exclude}>',
            '  <xsl:output method="xml" indent="yes" encoding="UTF-8"/>',
            *(["  <!-- XSLT 2.0: run with an XSLT 2.0+ processor (e.g. Saxon-HE). -->"] if self.v2 else []),
            *params,
            *variables,
            "",
            f"  <!-- Generated from {len(ws.mappings)} mapping(s), {n_stmts} statement(s), "
            f"{len(ws.variables)} variable(s) -->",
            '  <xsl:template match="/">',
            *body,
            "  </xsl:template>",
            *(self.copy_ns_template() if self.uses_copy_ns else []),
            "</xsl:stylesheet>",
            "",
        ])


def generate_xslt(ws: MappingWorkspace) -> str:
    return XsltWriter(ws).stylesheet()


def generate_xslt_snippet(ws: MappingWorkspace, target: str, scope: str = "") -> str:
    """Just the XSLT for one target node (with its statements and children),
    rendered in the for-each context its ancestors establish."""
    w = XsltWriter(ws)
    node, ctx = w.s.ancestors_ctx(target)
    if node is None:
        return f"<!-- {target} is not in the target tree -->"
    lines = w.node(node, ctx, [scope] if scope else [], 0)
    header = [f"<!-- context: for-each {w._absolute(c.source_id, c.path.split('.'))} -->" for c in ctx]
    return "\n".join(header + (lines or [f"<!-- {_tag(node)}: nothing mapped yet -->"]))


def formula_xpath(ws: MappingWorkspace, text: str, target: str, outer: bool = False) -> tuple[str, str]:
    """(XPath for a formula as it would appear at `target`, its evaluation context)."""
    w = XsltWriter(ws)
    ctx = (w.s.ancestors_ctx(target)[1] if outer else w.s.inner_ctx(target)) if target else []
    out = w.xp(parse_expr(text), [], ctx, single=True)
    if isinstance(out, dict):
        out = "xsl:choose (IF/WHEN)"
    context = w._absolute(ctx[-1].source_id, ctx[-1].path.split(".")) if ctx else "/ (document root)"
    return out, context

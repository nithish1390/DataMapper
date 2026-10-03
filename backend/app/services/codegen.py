"""
Java/XML code generation: a real MapStruct @Mapper interface (matching a
hand-written MapStruct mapper's style: @Mapping for direct fields,
expression="java(...)" for CONCAT/IF/WHEN/etc., @Named/qualifiedByName for a
single-argument custom or jar function), plus the matching XSLT, JAXB model
classes for XSD sources/targets, and the surrounding Spring Boot project
files (pom.xml, MappingRequest, REST controller, optional Camel adapter).
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.schemas import FieldNode, MappingWorkspace, ProjectSettings
from app.services.transform_dsl import (
    KNOWN_FUNCS, expr_to_java, expr_to_xpath, max_placeholder_index, parse_expr,
)


def pascal_case(s: str) -> str:
    words = re.split(r"[^a-zA-Z0-9]+", s.strip())
    out = "".join(w[:1].upper() + w[1:] for w in words if w)
    return out or "Model"


def camel_case(s: str) -> str:
    p = pascal_case(s)
    return p[:1].lower() + p[1:] if p else p


def source_var_name(idx: int) -> str:
    return f"source{idx + 1}"


def source_class_name(idx: int) -> str:
    return f"Source{idx + 1}Model"


def strip_array_suffix(seg: str) -> str:
    return seg[:-2] if seg.endswith("[]") else seg


# ----------------------------------------------------------- flattened POJO
def top_level_fields(fields: list[FieldNode]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for f in fields:
        first = re.split(r"[.\[]", f.path)[0]
        if first not in seen:
            seen[first] = "object" if ("." in f.path or "[" in f.path) else f.type
    return list(seen.items())


def generate_model_class(class_name: str, fields: list[FieldNode], pkg: str, use_lombok: bool) -> str:
    java_type = {"string": "String", "integer": "Integer", "number": "Double",
                 "boolean": "Boolean", "array": "List<Object>", "object": "Object"}
    flat = top_level_fields(fields)
    props = "\n".join(f"    private {java_type.get(t, 'String')} {camel_case(p)};" for p, t in flat)
    accessors = ""
    if not use_lombok:
        parts = []
        for p, t in flat:
            jt, name, pn = java_type.get(t, "String"), camel_case(p), pascal_case(p)
            parts.append(f"    public {jt} get{pn}() {{ return {name}; }}\n"
                         f"    public void set{pn}({jt} {name}) {{ this.{name} = {name}; }}")
        accessors = "\n\n" + "\n\n".join(parts)
    lombok_import = "\nimport lombok.Data;\n" if use_lombok else ""
    lombok_anno = "@Data\n" if use_lombok else ""
    return (f"package {pkg}.model;\n{lombok_import}\n"
            f"import java.util.List;\n\n"
            f"{lombok_anno}public class {class_name} {{\n\n{props}{accessors}\n}}\n")


# ---------------------------------------------------------- JAXB (XSD) tree
def xsd_tree_to_java_classes(tree: list[FieldNode], root_class_name: str, pkg: str) -> dict[str, str]:
    """One .java file per complex (object) node, JAXB-annotated."""
    java_leaf_type = {"string": "String", "integer": "Integer", "number": "Double", "boolean": "Boolean"}
    files: dict[str, str] = {}

    def build(nodes: list[FieldNode], class_name: str, is_doc_root: bool, value_type: Optional[str] = None) -> None:
        field_decls = []
        xml_imports = {"jakarta.xml.bind.annotation.XmlElement",
                        "jakarta.xml.bind.annotation.XmlAccessorType",
                        "jakarta.xml.bind.annotation.XmlAccessType"}
        if is_doc_root:
            xml_imports.add("jakarta.xml.bind.annotation.XmlRootElement")
        if value_type:  # simple content: the element's own text, next to its attributes
            xml_imports.add("jakarta.xml.bind.annotation.XmlValue")
            jt = java_leaf_type.get(value_type, "String")
            field_decls.append(("    @XmlValue\n    private " + jt + " value;", jt, "value", "Value"))
        for n in nodes:
            field_name = camel_case(strip_array_suffix(n.name))
            xml_name = strip_array_suffix(n.name)
            if n.name.startswith("@"):
                xml_imports.add("jakarta.xml.bind.annotation.XmlAttribute")
                jt = java_leaf_type.get(n.type, "String")
                req = ", required = true" if n.mandatory else ""
                field_decls.append((
                    f'    @XmlAttribute(name = "{xml_name[1:]}"{req})\n    private {jt} {field_name};',
                    jt, field_name, pascal_case(field_name)))
                continue
            if n.children and n.type not in ("object", "array"):
                nested_class = pascal_case(xml_name)
                build(n.children, nested_class, False, value_type=n.type)
                field_decls.append((
                    f'    @XmlElement(name = "{xml_name}")\n    private {nested_class} {field_name};',
                    nested_class, field_name, pascal_case(field_name)))
                continue
            if n.type == "object" and n.children:
                nested_class = pascal_case(xml_name)
                build(n.children, nested_class, False)
                field_decls.append((
                    f'    @XmlElement(name = "{xml_name}")\n    private {nested_class} {field_name};',
                    nested_class, field_name, pascal_case(field_name)))
            elif n.type == "array":
                if n.children:
                    nested_class = pascal_case(xml_name)
                    build(n.children, nested_class, False)
                    xml_imports.add("java.util.List")
                    field_decls.append((
                        f'    @XmlElement(name = "{xml_name}")\n    private List<{nested_class}> {field_name};',
                        f"List<{nested_class}>", field_name, pascal_case(field_name)))
                else:
                    xml_imports.add("java.util.List")
                    field_decls.append((
                        f'    @XmlElement(name = "{xml_name}")\n    private List<String> {field_name};',
                        "List<String>", field_name, pascal_case(field_name)))
            else:
                jt = java_leaf_type.get(n.type, "String")
                field_decls.append((
                    f'    @XmlElement(name = "{xml_name}")\n    private {jt} {field_name};',
                    jt, field_name, pascal_case(field_name)))
        accessors = "\n\n".join(
            f"    public {t} get{pn}() {{ return {name}; }}\n"
            f"    public void set{pn}({t} v) {{ this.{name} = v; }}"
            for _, t, name, pn in field_decls)
        root_anno = f'@XmlRootElement(name = "{class_name}")\n' if is_doc_root else ""
        content = (f"package {pkg};\n\n"
                   + "\n".join(f"import {i};" for i in sorted(xml_imports)) + "\n\n"
                   f"{root_anno}@XmlAccessorType(XmlAccessType.FIELD)\n"
                   f"public class {class_name} {{\n\n"
                   + "\n\n".join(d for d, *_ in field_decls) + "\n\n"
                   f"{accessors}\n}}\n")
        files[f"{class_name}.java"] = content

    build(tree, root_class_name, True)
    return files


# --------------------------------------------------------- MapStruct mapper
def _find_node(nodes: list[FieldNode], path: str) -> Optional[FieldNode]:
    for n in nodes:
        if n.path == path:
            return n
        hit = _find_node(n.children, path)
        if hit:
            return hit
    return None


def _is_simple_content(node: Optional[FieldNode]) -> bool:
    """An element with attributes and its own value (e.g. InstdAmt + @Ccy) -> JAXB @XmlValue."""
    return bool(node and node.children and node.type not in ("object", "array")
                and all(c.name.startswith("@") for c in node.children))


def _mapstruct_source_expr(inp, sources, for_java: bool) -> str:
    idx = next((i for i, s in enumerate(sources) if s.id == inp.source_id), -1)
    src = sources[idx] if idx >= 0 else None
    var_name = source_var_name(idx if idx >= 0 else 0)
    if src and src.type in ("xsd", "xml"):
        segs = [strip_array_suffix(s) for s in inp.path.split(".")]
        if _is_simple_content(_find_node(src.fields, inp.path)):
            segs.append("value")
        if for_java:
            return var_name + "".join(f".get{pascal_case(s)}()" for s in segs)
        return var_name + "." + ".".join(camel_case(s) for s in segs)
    first = re.split(r"[.\[]", inp.path)[0]
    return f"{var_name}.get{pascal_case(first)}()" if for_java else f"{var_name}.{camel_case(first)}"


def _mapstruct_target_path(target: str, target_is_xsd: bool) -> str:
    if target_is_xsd:
        return ".".join(camel_case(strip_array_suffix(s)) for s in target.split("."))
    return camel_case(re.split(r"[.\[]", target)[0])


def _flatten_nodes(nodes: list[FieldNode]) -> list[FieldNode]:
    out: list[FieldNode] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten_nodes(n.children))
    return out


def generate_mapstruct_mapper(ws: MappingWorkspace) -> tuple[str, set[str]]:
    """Returns (java source, custom function names used)."""
    pkg = ws.project.package
    target_is_xsd = ws.target.type in ("xsd", "xml")

    def tpath(target: str, is_xsd: bool) -> str:
        base = _mapstruct_target_path(target, is_xsd)
        return base + ".value" if is_xsd and _is_simple_content(_find_node(ws.target.fields, target)) else base
    jar_functions = [jf.model_dump(by_alias=False) for jf in ws.jar_functions]
    for jf in jar_functions:
        jf["method_name"] = jf.pop("method_name", jf.get("methodName"))
        jf["class_name"] = jf.get("class_name", jf.get("className"))

    custom_funcs_used: set[str] = set()
    jar_imports_used: set[str] = set()

    # Variables: MapStruct's generated code has no shared local scope, so a
    # $variable is inlined with its own compiled expression wherever used.
    var_inline: dict[str, str] = {}
    for v in ws.variables:
        args_java = [_mapstruct_source_expr(inp, ws.sources, True) for inp in v.inputs]
        node = parse_expr(v.transform or ("{0}" if args_java else "''"))
        var_inline[v.name] = expr_to_java(node, args_java, custom_funcs_used, jar_imports_used,
                                           jar_functions, var_inline)

    named_methods: list[tuple[str, str]] = []
    mapping_lines: list[str] = []

    from app.models.schemas import SourceRef
    from app.services.structure import Structure, branch_key, otherwise_key
    struct = Structure(ws)

    def ref_source(ref, target: str) -> SourceRef:
        sid, segs = struct.resolve_abs(ref, struct.inner_ctx(target))
        return SourceRef(source_id=sid, path=struct.tree_path(sid, segs) or ".".join(segs))

    def java_expr(text: str, inputs, target: str) -> str:
        args_java = [_mapstruct_source_expr(i, ws.sources, True) for i in inputs]
        node = parse_expr(text if text.strip() else ("{0}" if args_java else "null"))
        return expr_to_java(node, args_java, custom_funcs_used, jar_imports_used, jar_functions, var_inline,
                            lambda r: _mapstruct_source_expr(ref_source(r, target), ws.sources, True))

    # Structure statements. MapStruct is declarative: leaf-level if/choose
    # compile into a conditional expression; for-each, branch-scoped mappings
    # and statements on container elements need hand-written @Mapper methods,
    # so they're listed as TODOs (the XSLT output implements them fully).
    leaf_paths = {n.path for n in _flatten_nodes(ws.target.fields) if not n.children}
    structure_todos: list[str] = []
    handled: set[str] = set()
    for (target, scope), stmts in struct.structs.items():
        loops = [st for st in stmts if st.kind in ("for-each", "for-each-group")]
        conds = [st for st in stmts if st.kind not in ("for-each", "for-each-group")]
        if loops or scope or target not in leaf_paths:
            for st in stmts:
                what = (st.select or (st.inputs[0].path if st.inputs else "") if st.kind in ("for-each", "for-each-group")
                        else st.test or " | ".join(w.test for w in st.whens))
                structure_todos.append(f"    // TODO {st.kind} on {target}{' [' + scope + ']' if scope else ''}: {what}")
            continue
        if not conds:
            continue
        m = struct.maps.get((target, ""))
        expr = java_expr(m.transform, m.inputs, target) if m else "null"
        for st in reversed(conds):
            if st.kind == "if":
                cond = java_expr(st.test or "EXISTS({0})", st.inputs, target)
                expr = f"({cond} ? {expr} : null)"
                continue

            def branch_value(key: str, legacy: str, fallback: str) -> str:
                bm = struct.maps.get((target, key))
                if bm:
                    return java_expr(bm.transform, bm.inputs, target)
                return java_expr(legacy, st.inputs, target) if legacy.strip() else fallback

            tail = branch_value(otherwise_key(st), st.otherwise or "", expr) if st.otherwise is not None else "null"
            for i in reversed(range(len(st.whens))):
                w = st.whens[i]
                tail = (f"({java_expr(w.test or 'true()', st.inputs, target)} ? "
                        f"{branch_value(branch_key(st, i), w.value, expr)} : {tail})")
            expr = tail
        mapping_lines.append(f'    @Mapping(target = "{tpath(target, target_is_xsd)}", '
                             f'expression = "java({expr})")')
        handled.add(target)

    for m in ws.mappings:
        target_path = tpath(m.target, target_is_xsd)
        if m.target in handled or m.scope:
            continue
        node = parse_expr(m.transform)
        single_ref = node.type == "ref" and not m.inputs
        if m.mode == "copy-of" and (m.inputs or single_ref):
            src = m.inputs[0] if m.inputs else ref_source(node, m.target)
            mapping_lines.append(
                f'    @Mapping(source = "{_mapstruct_source_expr(src, ws.sources, False)}", '
                f'target = "{target_path}") // copy-of')
            continue
        if m.for_each:
            mapping_lines.append(f'    @Mapping(target = "{target_path}", ignore = true) '
                                  f'// TODO: repeating element — needs a dedicated per-item @Mapper method')
            continue
        if not m.inputs and not m.transform.strip():
            mapping_lines.append(f'    @Mapping(target = "{target_path}", ignore = true) // no source mapped yet')
            continue
        if single_ref:
            mapping_lines.append(
                f'    @Mapping(source = "{_mapstruct_source_expr(ref_source(node, m.target), ws.sources, False)}", '
                f'target = "{target_path}")')
            continue
        if not m.inputs:
            mapping_lines.append(f'    @Mapping(target = "{target_path}", '
                                 f'expression = "java({java_expr(m.transform, [], m.target)})")')
            continue

        is_single_arg_custom = (node.type == "call" and len(node.args) == 1
                                 and node.args[0].type == "placeholder" and node.args[0].index == 0
                                 and len(m.inputs) == 1 and node.func not in KNOWN_FUNCS)

        if not m.transform or not m.transform.strip():
            if len(m.inputs) == 1:
                mapping_lines.append(
                    f'    @Mapping(source = "{_mapstruct_source_expr(m.inputs[0], ws.sources, False)}", '
                    f'target = "{target_path}")')
            else:
                args_java = [_mapstruct_source_expr(i, ws.sources, True) for i in m.inputs]
                concat = "CONCAT(" + ", ".join(f"{{{i}}}" for i in range(len(m.inputs))) + ")"
                expr = expr_to_java(parse_expr(concat), args_java, custom_funcs_used, jar_imports_used,
                                     jar_functions, var_inline)
                mapping_lines.append(f'    @Mapping(target = "{target_path}", expression = "java({expr})")')
            continue

        if is_single_arg_custom:
            jf = next((j for j in jar_functions if j["method_name"].upper() == node.func), None)
            method_name = jf["method_name"] if jf else (node.func_raw or node.func.lower())
            if not any(n == method_name for n, _ in named_methods):
                if jf:
                    body = (f'    @Named("{method_name}")\n'
                            f"    default Object {method_name}(Object value) {{\n"
                            f"        return {jf['class_name'].split('.')[-1]}.{jf['method_name']}(value);\n"
                            f"    }}")
                    jar_imports_used.add(jf["class_name"])
                else:
                    custom_funcs_used.add(method_name)
                    body = (f'    @Named("{method_name}")\n'
                            f"    default Object {method_name}(Object value) {{\n"
                            f"        return CustomFunctions.{method_name}(value); "
                            f"// TODO: implement in CustomFunctions.java\n    }}")
                named_methods.append((method_name, body))
            mapping_lines.append(
                f'    @Mapping(source = "{_mapstruct_source_expr(m.inputs[0], ws.sources, False)}", '
                f'target = "{target_path}", qualifiedByName = "{method_name}")')
            continue

        expr = java_expr(m.transform, m.inputs, m.target)
        mapping_lines.append(f'    @Mapping(target = "{target_path}", expression = "java({expr})")')

    params = ", ".join(f"{source_class_name(i)} {source_var_name(i)}" for i in range(len(ws.sources)))
    arg_names = ", ".join(source_var_name(i) for i in range(len(ws.sources)))
    use_root_condition = bool(ws.root_condition.transform.strip() and ws.root_condition.inputs)
    abstract_method = "mapInternal" if use_root_condition else "map"

    root_wrapper = ""
    if use_root_condition:
        root_wrapper = (
            f"\n\n    /**\n"
            f"     * Root condition: {ws.root_condition.transform}\n"
            f"     * Inputs: {', '.join(i.source_id + '.' + i.path for i in ws.root_condition.inputs)}\n"
            f"     * TODO: evaluate the condition and return null when it is not satisfied — MapStruct\n"
            f"     * mapper interfaces are declarative, so this wrapper is where an imperative\n"
            f"     * pre-check like this has to live.\n"
            f"     */\n"
            f"    default TargetModel map({params}) {{\n"
            f"        return mapInternal({arg_names});\n"
            f"    }}")

    model_imports = {f"{pkg}.model.*"}
    for i, s in enumerate(ws.sources):
        if s.type in ("xsd", "xml"):
            model_imports.add(f"{pkg}.model.xsd{i + 1}.*")
    if target_is_xsd:
        model_imports.add(f"{pkg}.model.xsdtarget.*")

    jar_import_lines = "\n".join(f"import {c};" for c in sorted(jar_imports_used))
    source = (
        f"package {pkg}.mapper;\n\n"
        f"import org.mapstruct.Mapper;\n"
        f"import org.mapstruct.Mapping;\n"
        f"import org.mapstruct.Named;\n"
        f"import org.mapstruct.factory.Mappers;\n"
        + "\n".join(f"import {i};" for i in sorted(model_imports)) + "\n"
        + (jar_import_lines + "\n" if jar_import_lines else "") +
        f"\n/**\n"
        f" * Generated by MapSheet AI as a declarative MapStruct mapper.\n"
        f" * {len(ws.mappings)} field mapping(s), {len(ws.variables)} variable(s) inlined"
        f"{', root condition applied' if use_root_condition else ''}.\n"
        f" */\n"
        f"@Mapper\n"
        f"public interface FieldMapperProcessor {{\n\n"
        f"    FieldMapperProcessor INSTANCE = Mappers.getMapper(FieldMapperProcessor.class);\n\n"
        + "\n".join(mapping_lines) + "\n"
        + ("\n".join(structure_todos) + "\n" if structure_todos else "") +
        f"    TargetModel {abstract_method}({params});\n"
        f"{root_wrapper}\n"
        + ("\n" + "\n\n".join(b for _, b in named_methods) if named_methods else "") +
        "\n}\n"
    )
    return source, custom_funcs_used


def generate_camel_processor_wrapper(ws: MappingWorkspace) -> str:
    pkg = ws.project.package
    target_import = f"{pkg}.model.xsdtarget.TargetModel" if ws.target.type in ("xsd", "xml") else f"{pkg}.model.TargetModel"
    args = ", ".join(f"req.get{source_class_name(i)}()" for i in range(len(ws.sources)))
    return (
        f"package {pkg}.mapper;\n\n"
        f"import org.apache.camel.Exchange;\n"
        f"import org.apache.camel.Processor;\n"
        f"import {pkg}.model.MappingRequest;\n"
        f"import {target_import};\n"
        f"import org.springframework.stereotype.Component;\n\n"
        f"/** Adapts the declarative FieldMapperProcessor (MapStruct) for use as a Camel route step. */\n"
        f"@Component\n"
        f"public class CamelMappingProcessor implements Processor {{\n\n"
        f"    @Override\n"
        f"    public void process(Exchange exchange) {{\n"
        f"        MappingRequest req = exchange.getIn().getBody(MappingRequest.class);\n"
        f"        TargetModel result = FieldMapperProcessor.INSTANCE.map({args});\n"
        f"        exchange.getIn().setBody(result);\n"
        f"    }}\n}}\n"
    )


def generate_custom_functions_class(pkg: str, funcs: set[str]) -> str:
    methods = "\n\n".join(
        f"    /** TODO: implement {f} — invoked from a mapping transform of the same name. */\n"
        f"    public static Object {f}(Object... args) {{\n"
        f"        return args.length > 0 ? args[0] : null;\n    }}"
        for f in sorted(funcs))
    return (f"package {pkg}.mapper;\n\n"
            f"/** Stub implementations for custom transform functions referenced in the mapper UI. */\n"
            f"public class CustomFunctions {{\n\n{methods}\n}}\n")


# ------------------------------------------------------------------- XSLT
# Lives in xslt_gen.py (structure-aware: for-each / if / choose / copy-of).
from app.services.xslt_gen import generate_xslt  # noqa: E402,F401


# --------------------------------------------------------- project scaffold
def generate_pom(ws: MappingWorkspace) -> str:
    p = ws.project
    mapstruct_version = "1.6.3"
    deps = [f'    <dependency>\n      <groupId>org.mapstruct</groupId>\n'
            f'      <artifactId>mapstruct</artifactId>\n      <version>{mapstruct_version}</version>\n    </dependency>']
    if p.dep_web:
        deps.append('    <dependency>\n      <groupId>org.springframework.boot</groupId>\n'
                     '      <artifactId>spring-boot-starter-web</artifactId>\n    </dependency>')
    if p.dep_jackson:
        deps.append('    <dependency>\n      <groupId>com.fasterxml.jackson.core</groupId>\n'
                     '      <artifactId>jackson-databind</artifactId>\n    </dependency>')
    if p.dep_lombok:
        deps.append('    <dependency>\n      <groupId>org.projectlombok</groupId>\n'
                     '      <artifactId>lombok</artifactId>\n      <optional>true</optional>\n    </dependency>')
    if p.dep_camel:
        deps.append('    <dependency>\n      <groupId>org.apache.camel.springboot</groupId>\n'
                     '      <artifactId>camel-spring-boot-starter</artifactId>\n      <version>4.6.0</version>\n    </dependency>')
    any_xsd = any(s.type in ("xsd", "xml") for s in ws.sources) or ws.target.type in ("xsd", "xml")
    if any_xsd:
        deps.append('    <dependency>\n      <groupId>jakarta.xml.bind</groupId>\n'
                     '      <artifactId>jakarta.xml.bind-api</artifactId>\n      <version>4.0.2</version>\n    </dependency>\n'
                     '    <dependency>\n      <groupId>org.glassfish.jaxb</groupId>\n'
                     '      <artifactId>jaxb-runtime</artifactId>\n      <version>4.0.5</version>\n    </dependency>')

    annotation_paths = [f'              <path>\n                <groupId>org.mapstruct</groupId>\n'
                         f'                <artifactId>mapstruct-processor</artifactId>\n'
                         f'                <version>{mapstruct_version}</version>\n              </path>']
    if p.dep_lombok:
        annotation_paths.insert(0, '              <path>\n                <groupId>org.projectlombok</groupId>\n'
                                    '                <artifactId>lombok</artifactId>\n'
                                    '                <version>1.18.34</version>\n              </path>')
        annotation_paths.append('              <path>\n                <groupId>org.projectlombok</groupId>\n'
                                 '                <artifactId>lombok-mapstruct-binding</artifactId>\n'
                                 '                <version>0.2.0</version>\n              </path>')

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>{p.boot_version}</version>
    <relativePath/>
  </parent>
  <groupId>{p.group}</groupId>
  <artifactId>{p.artifact}</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <name>{p.artifact}</name>
  <properties><java.version>{p.java_version}</java.version></properties>
  <dependencies>
{chr(10).join(deps)}
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration>
          <annotationProcessorPaths>
{chr(10).join(annotation_paths)}
          </annotationProcessorPaths>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
"""


def generate_application_java(pkg: str, artifact: str) -> str:
    cls = pascal_case(artifact) + "Application"
    return (f"package {pkg};\n\n"
            f"import org.springframework.boot.SpringApplication;\n"
            f"import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n"
            f"@SpringBootApplication\n"
            f"public class {cls} {{\n"
            f"    public static void main(String[] args) {{ SpringApplication.run({cls}.class, args); }}\n}}\n")


def generate_mapping_request(ws: MappingWorkspace) -> str:
    pkg = ws.project.package
    fields = []
    imports = []
    for i, s in enumerate(ws.sources):
        cls, var = source_class_name(i), source_var_name(i)
        fields.append(f"    private {cls} {var};\n\n"
                       f"    public {cls} get{cls}() {{ return {var}; }}\n"
                       f"    public void set{cls}({cls} v) {{ this.{var} = v; }}")
        if s.type in ("xsd", "xml"):
            imports.append(f"import {pkg}.model.xsd{i + 1}.{cls};")
    import_block = ("\n" + "\n".join(imports) + "\n") if imports else ""
    return (f"package {pkg}.model;\n{import_block}\n"
            f"/** Wrapper request carrying one payload per configured source, "
            f'e.g. {{"source1": {{...}}, "source2": {{...}}}}. */\n'
            f"public class MappingRequest {{\n\n{chr(10).join(fields)}\n}}\n")


def generate_controller(ws: MappingWorkspace) -> str:
    pkg = ws.project.package
    target_import = f"{pkg}.model.xsdtarget.TargetModel" if ws.target.type in ("xsd", "xml") else f"{pkg}.model.TargetModel"
    args = ", ".join(f"req.get{source_class_name(i)}()" for i in range(len(ws.sources)))
    return (f"package {pkg}.controller;\n\n"
            f"import {pkg}.mapper.FieldMapperProcessor;\n"
            f"import {pkg}.model.MappingRequest;\n"
            f"import {target_import};\n"
            f"import org.springframework.web.bind.annotation.*;\n\n"
            f'@RestController\n@RequestMapping("/api")\n'
            f"public class MappingController {{\n\n"
            f'    @PostMapping("/map")\n'
            f"    public TargetModel map(@RequestBody MappingRequest req) {{\n"
            f"        return FieldMapperProcessor.INSTANCE.map({args});\n    }}\n}}\n")


def generate_yml(ws: MappingWorkspace) -> str:
    return f"server:\n  port: 8080\n\nspring:\n  application:\n    name: {ws.project.artifact}\n"


def generate_readme(ws: MappingWorkspace, mapper_java: str) -> str:
    p = ws.project
    sources_desc = "; ".join(f"{s.label} ({s.type}, {len(s.fields)} field(s))" for s in ws.sources)
    return f"""# {p.artifact}

Generated by MapSheet AI.

- Sources: {sources_desc}
- Target: {ws.target.type} ({len(ws.target.fields)} field(s))
- Mappings: {len(ws.mappings)}; variables: {len(ws.variables)}

## Run

```
mvn spring-boot:run
```

POST a MappingRequest JSON body (one key per source) to `/api/map`.

## Notes

- `FieldMapperProcessor` is a MapStruct `@Mapper` interface — MapStruct's annotation processor
  generates the implementation at build time; nothing to hand-write there.
- Any source or target defined as XSD gets real nested JAXB-annotated classes
  (`model.xsdN` / `model.xsdtarget`), not a flattened POJO.
- `for-each` mappings are marked `ignore = true` with a TODO — a repeating element needs its own
  dedicated `@Mapper` method for the item type.
"""

"""
Format parsers: every source/target format is converted into the same
FieldNode tree shape, so the rest of the backend (and the whole frontend)
never needs to know which format a field originally came from.

This is a direct port of the parsing logic from the original single-file
prototype, translated to Python, with the same normalization/fuzzy-matching
behavior for path resolution.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.schemas import FieldNode

def norm_type(t: Optional[str]) -> str:
    if not t:
        return "object"
    t = str(t).lower()
    if "int" in t or t in ("long", "short", "byte"):
        return "integer"
    if "double" in t or "float" in t or "decimal" in t or t == "number":
        return "number"
    if "bool" in t:
        return "boolean"
    if "list" in t or "array" in t or "[]" in t or "set" in t:
        return "array"
    if "string" in t or t in ("str", "char"):
        return "string"
    if t == "object" or "map" in t:
        return "object"
    return "string"


# ---------------------------------------------------------------- JSON Schema
def _resolve_ref(root: dict, ref: str) -> Optional[dict]:
    if not ref or not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    node: Any = root
    for part in parts:
        if node is None:
            return None
        part = part.replace("~1", "/").replace("~0", "~")
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _resolve_schema(root: dict, schema: dict, hops: int = 0) -> dict:
    if schema and "$ref" in schema and hops < 8:
        target = _resolve_ref(root, schema["$ref"])
        if target is not None:
            return _resolve_schema(root, target, hops + 1)
    return schema or {}


def _build_schema_tree(props: dict, prefix: str, depth: int, root: dict,
                        required: Optional[list[str]]) -> list[FieldNode]:
    if not props or depth > 6:
        return []
    req = set(required or [])
    out: list[FieldNode] = []
    for key, raw in props.items():
        p = _resolve_schema(root, raw or {}, 0)
        path = f"{prefix}.{key}" if prefix else key
        t = p.get("type")
        if isinstance(t, list):
            t = t[0] if t else None
        if not t and p.get("properties"):
            t = "object"
        if not t and p.get("items"):
            t = "array"
        mandatory = key in req
        if t == "object" or p.get("properties"):
            out.append(FieldNode(name=key, path=path, type="object", mandatory=mandatory,
                                  children=_build_schema_tree(p.get("properties") or {}, path,
                                                               depth + 1, root, p.get("required"))))
        elif t == "array":
            items = _resolve_schema(root, p.get("items") or {}, 0)
            if items.get("properties"):
                out.append(FieldNode(name=f"{key}[]", path=f"{path}[]", type="array", mandatory=mandatory,
                                      children=_build_schema_tree(items["properties"], f"{path}[]",
                                                                   depth + 1, root, items.get("required"))))
            else:
                out.append(FieldNode(name=f"{key}[]", path=f"{path}[]", type="array",
                                      mandatory=mandatory, children=[]))
        else:
            out.append(FieldNode(name=key, path=path, type=norm_type(t), mandatory=mandatory, children=[]))
    return out


def parse_json_schema(text: str) -> tuple[list[FieldNode], Optional[str]]:
    obj = _load_structured(text)
    if not isinstance(obj, dict):
        raise ValueError("A JSON Schema is an object with \"properties\".")
    if obj.get("type") == "array" and isinstance(obj.get("items"), dict):
        items = _resolve_schema(obj, obj["items"], 0)
        return [FieldNode(name=f"{ROOT_ARRAY}[]", path=f"{ROOT_ARRAY}[]", type="array",
                          children=_build_schema_tree(items.get("properties") or {}, f"{ROOT_ARRAY}[]", 0, obj,
                                                      items.get("required")))], None
    root_schema = obj
    if not obj.get("properties"):
        bag = obj.get("$defs") or obj.get("definitions")
        if bag:
            best_name, best_count = next(iter(bag)), -1
            for name, sub in bag.items():
                count = len((sub or {}).get("properties") or {})
                if count > best_count:
                    best_name, best_count = name, count
            root_schema = bag[best_name]
    root_schema = _resolve_schema(obj, root_schema, 0)
    tree = _build_schema_tree(root_schema.get("properties") or {}, "", 0, obj, root_schema.get("required"))
    if not tree:
        raise ValueError('No "properties" found in schema.')
    return tree, None


# ------------------------------------------------------------- JSON sample
ROOT_ARRAY = "items"  # name given to a top-level JSON array (Test / Run wraps the sample the same way)


def _infer_scalar(val: Any) -> str:
    if val is None:
        return "string"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    return "string"


def _merge_objects(items: list) -> dict:
    """Union of keys over the objects of an array (later items may add keys)."""
    merged: dict = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        for k, v in it.items():
            if k not in merged or merged[k] is None:
                merged[k] = v
            elif isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = _merge_objects([merged[k], v])
            elif isinstance(merged[k], list) and isinstance(v, list):
                merged[k] = merged[k] + v
    return merged


def _sample_node(key: str, val: Any, prefix: str, depth: int) -> FieldNode:
    path = f"{prefix}.{key}" if prefix else key
    if isinstance(val, dict):
        return FieldNode(name=key, path=path, type="object", children=_build_sample_tree(val, path, depth + 1))
    if isinstance(val, list):
        objs = [v for v in val if isinstance(v, dict)]
        if objs:
            return FieldNode(name=f"{key}[]", path=f"{path}[]", type="array",
                             children=_build_sample_tree(_merge_objects(objs), f"{path}[]", depth + 1))
        return FieldNode(name=f"{key}[]", path=f"{path}[]", type="array", children=[])
    return FieldNode(name=key, path=path, type=_infer_scalar(val), children=[])


def _build_sample_tree(obj: dict, prefix: str, depth: int) -> list[FieldNode]:
    if not obj or depth > 12:
        return []
    return [_sample_node(k, v, prefix, depth) for k, v in obj.items()]


def _load_structured(text: str) -> Any:
    """JSON, or YAML (OpenAPI / schemas / samples are often written in YAML)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_err:
        try:
            import yaml
        except ImportError:
            raise ValueError(f"Not valid JSON: {json_err}") from json_err
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            raise ValueError(f"Not valid JSON or YAML: {json_err}") from json_err
        if not isinstance(data, (dict, list)):
            raise ValueError(f"Not valid JSON or YAML: {json_err}") from json_err
        return data


def parse_json_object(text: str) -> tuple[list[FieldNode], Optional[str]]:
    obj = _load_structured(text)
    if isinstance(obj, list):
        tree = [_sample_node(ROOT_ARRAY, obj, "", 0)]
    elif isinstance(obj, dict):
        tree = _build_sample_tree(obj, "", 0)
    else:
        raise ValueError("Expected a JSON object or array.")
    if not tree:
        raise ValueError("Empty object.")
    return tree, None


# -------------------------------------------------------------- XML sample
def _infer_text(v: str) -> str:
    v = (v or "").strip()
    if v.lower() in ("true", "false"):
        return "boolean"
    if re.fullmatch(r"-?\d+", v):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", v):
        return "number"
    return "string"


def parse_xml_sample(text: str) -> tuple[list[FieldNode], Optional[str]]:
    """An XML instance -> tree: repeated elements become arrays (structure merged over all
    occurrences), attributes become @name fields, values typed from their text."""
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    def build(elements: list[ET.Element], name: str, path: str, repeated: bool, depth: int) -> FieldNode:
        out_name, out_path = (f"{name}[]", f"{path}[]") if repeated else (name, path)
        attrs: dict[str, str] = {}
        child_groups: dict[str, list[ET.Element]] = {}
        child_repeats: dict[str, bool] = {}
        texts = []
        for el in elements:
            for k, v in el.attrib.items():
                if not k.startswith("{http://www.w3.org/2001/XMLSchema-instance}"):
                    attrs.setdefault(_local(k), v)
            counts: dict[str, int] = {}
            for c in el:
                if not isinstance(c.tag, str):
                    continue
                ln = _local(c.tag)
                child_groups.setdefault(ln, []).append(c)
                counts[ln] = counts.get(ln, 0) + 1
            for ln, n in counts.items():
                child_repeats[ln] = child_repeats.get(ln, False) or n > 1
            if el.text and el.text.strip():
                texts.append(el.text.strip())
        children = [FieldNode(name=f"@{k}", path=f"{out_path}.@{k}", type=_infer_text(v)) for k, v in attrs.items()]
        if depth < 15:
            children += [build(els, ln, f"{out_path}.{ln}", child_repeats.get(ln, False), depth + 1)
                         for ln, els in child_groups.items()]
        has_elements = any(not c.name.startswith("@") for c in children)
        if repeated:
            node_type = "array"
        elif has_elements:
            node_type = "object"
        else:
            node_type = _infer_text(texts[0]) if texts else ("object" if children else "string")
        return FieldNode(name=out_name, path=out_path, type=node_type, children=children)

    tree = [build([root], _local(root.tag), _local(root.tag), False, 0)]
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else None
    return tree, ns


# --------------------------------------------------------------------- XSD
def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_xsd(text: str) -> tuple[list[FieldNode], Optional[str]]:
    xml_text = text.strip()
    if not xml_text.startswith("<?xml") and "<xs:schema" not in xml_text and "<schema" not in xml_text:
        xml_text = f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{xml_text}</xs:schema>'
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    is_schema_root = _local(root.tag) == "schema"
    complex_types: dict[str, ET.Element] = {}
    for el in root.iter():
        if _local(el.tag) == "complexType" and el.get("name"):
            complex_types[el.get("name")] = el
    global_elements = [c for c in root if _local(c.tag) == "element"] if is_schema_root else []

    in_choice: dict[int, str] = {}  # element -> its xs:choice group (alternatives are never mandatory)
    choice_ids: dict[int, str] = {}

    def direct_child_elements(complex_type_el: ET.Element) -> list[ET.Element]:
        out: list[ET.Element] = []

        def walk(node: ET.Element, choice: Optional[str]) -> None:
            for child in node:
                tag = _local(child.tag)
                if tag == "element":
                    out.append(child)
                    if choice:
                        in_choice[id(child)] = choice
                elif tag == "complexType":
                    continue
                else:
                    group = choice
                    if tag == "choice":
                        group = choice_ids.setdefault(id(child), f"c{len(choice_ids) + 1}")
                    walk(child, group)

        walk(complex_type_el, None)
        return out

    def strip_prefix(qn: str) -> str:
        return qn.split(":")[-1] if qn else qn

    simple_types: dict[str, ET.Element] = {}
    attr_groups: dict[str, ET.Element] = {}
    for el in root.iter():
        if _local(el.tag) == "simpleType" and el.get("name"):
            simple_types[el.get("name")] = el
        elif _local(el.tag) == "attributeGroup" and el.get("name"):
            attr_groups[el.get("name")] = el

    def resolve_simple(type_name: Optional[str], hops: int = 0) -> str:
        """Follows named simpleType restrictions down to the built-in xs: type."""
        name = strip_prefix(type_name or "string")
        st = simple_types.get(name)
        if st is None or hops > 10:
            return norm_type(name)
        restr = next((c for c in st.iter() if _local(c.tag) == "restriction" and c.get("base")), None)
        return resolve_simple(restr.get("base"), hops + 1) if restr is not None else "string"

    def attributes_of(complex_el: ET.Element) -> list[ET.Element]:
        out: list[ET.Element] = []

        def walk(node: ET.Element) -> None:
            for ch in node:
                tag = _local(ch.tag)
                if tag == "attribute":
                    out.append(ch)
                elif tag == "attributeGroup" and ch.get("ref"):
                    grp = attr_groups.get(strip_prefix(ch.get("ref")))
                    if grp is not None:
                        walk(grp)
                elif tag in ("element", "complexType"):
                    continue
                else:
                    walk(ch)

        walk(complex_el)
        return out

    def attribute_nodes(complex_el: ET.Element, owner_path: str) -> list[FieldNode]:
        nodes = []
        for a in attributes_of(complex_el):
            name = a.get("name") or strip_prefix(a.get("ref") or "")
            if not name or a.get("use") == "prohibited":
                continue
            nodes.append(FieldNode(name=f"@{name}", path=f"{owner_path}.@{name}", type=resolve_simple(a.get("type")),
                                   mandatory=a.get("use") == "required", children=[]))
        return nodes

    def simple_content_type(complex_el: ET.Element) -> Optional[str]:
        sc = next((c for c in complex_el if _local(c.tag) == "simpleContent"), None)
        if sc is None:
            return None
        ext = next((c for c in sc if _local(c.tag) in ("extension", "restriction") and c.get("base")), None)
        return resolve_simple(ext.get("base")) if ext is not None else "string"

    def build_from_element(el: ET.Element, prefix: str, depth: int,
                            visited: frozenset[int]) -> Optional[FieldNode]:
        if depth > 10:
            return None
        name = el.get("name")
        ref_attr = el.get("ref")
        if not name and ref_attr:
            target = next((g for g in global_elements if g.get("name") == strip_prefix(ref_attr)), None)
            return build_from_element(target, prefix, depth + 1, visited) if target is not None else None
        if not name:
            return None
        path = f"{prefix}.{name}" if prefix else name
        max_occurs = el.get("maxOccurs")
        is_repeating = bool(max_occurs) and max_occurs != "1"
        min_occurs = el.get("minOccurs")
        mandatory = (min_occurs is None or min_occurs != "0") and id(el) not in in_choice
        choice = f"{prefix}#{in_choice[id(el)]}" if id(el) in in_choice else None
        type_attr = el.get("type")
        inline_complex = next((c for c in el if _local(c.tag) == "complexType"), None)
        complex_el = inline_complex if inline_complex is not None else (
            complex_types.get(strip_prefix(type_attr)) if type_attr else None)
        out_name = f"{name}[]" if is_repeating else name
        out_path = f"{path}[]" if is_repeating else path
        if complex_el is not None:
            if id(complex_el) in visited:
                return FieldNode(name=out_name, path=out_path, type="array" if is_repeating else "object",
                                  mandatory=mandatory, children=[])
            next_visited = visited | {id(complex_el)}
            attrs = attribute_nodes(complex_el, out_path)
            children = attrs + [c for c in (build_from_element(ce, out_path, depth + 1, next_visited)
                                            for ce in direct_child_elements(complex_el)) if c]
            value_type = simple_content_type(complex_el)  # e.g. an amount with a Ccy attribute
            node_type = "array" if is_repeating else (value_type or "object")
            return FieldNode(name=out_name, path=out_path, type=node_type,
                              mandatory=mandatory, children=children, choice=choice)
        simple_type = resolve_simple(type_attr) if type_attr else "string"
        return FieldNode(name=out_name, path=out_path, type="array" if is_repeating else simple_type,
                          mandatory=mandatory, children=[], choice=choice)

    if is_schema_root:
        seeds = global_elements
    elif _local(root.tag) == "element":
        seeds = [root]
    else:
        seeds = [c for c in root if _local(c.tag) == "element"]

    trees = [t for t in (build_from_element(e, "", 0, frozenset()) for e in seeds) if t]
    if not trees:
        raise ValueError('No <xs:element name="..."> tags found.')
    return trees, None


# --------------------------------------------------------------------- CSV
def _csv_delimiter(lines: list[str]) -> str:
    """The delimiter (, ; tab |) that splits most lines into the same number (> 1) of columns."""
    import csv
    filled = [l for l in lines if l.strip()][:50]
    best, score = ",", (0, 0)
    for d in (",", ";", "\t", "|"):
        counts = [len(r) for r in csv.reader(filled, delimiter=d)]
        multi = [n for n in counts if n > 1]
        if not multi:
            continue
        width = max(set(multi), key=multi.count)
        sc = (multi.count(width), width)
        if sc > score:
            best, score = d, sc
    return best


def _csv_reader_rows(lines: list[str], delimiter: Optional[str] = None) -> list[list[str]]:
    import csv
    return list(csv.reader(lines, delimiter=delimiter or _csv_delimiter(lines)))


def csv_detect_header(text: str) -> int:
    """1-based line of the header: the first line with as many columns as most lines have (title or
    comment lines above the table are skipped)."""
    lines = text.lstrip("\ufeff").splitlines()
    filled = [(i + 1, l) for i, l in enumerate(lines) if l.strip()]
    if not filled:
        return 1
    d = _csv_delimiter(lines)
    counts = [len(r) for r in _csv_reader_rows([l for _n, l in filled], d)]
    width = max(set(counts), key=counts.count)
    return next((n for (n, _l), c in zip(filled, counts) if c == width), filled[0][0])


def csv_table(text: str, header_row: Optional[int] = 1) -> tuple[list[str], list[list[str]], int]:
    """(field names, data rows, header line used). `header_row` is the 1-based line number of the
    header in the text (blank lines count, as in an editor); 0 = no header row (column1, column2, …);
    None = detect it. Data rows are the non-empty lines below the header."""
    lines = text.lstrip("\ufeff").splitlines()
    if not any(l.strip() for l in lines):
        return [], [], 0
    if header_row is None:
        header_row = csv_detect_header(text)
    if header_row < 0:
        raise ValueError("Header row must be 0 (no header) or a line number.")
    if header_row > len(lines):
        raise ValueError(f"Header row {header_row} doesn't exist — the text has {len(lines)} line(s).")
    if header_row and not lines[header_row - 1].strip():
        raise ValueError(f"Line {header_row} is empty — choose the line that holds the column names.")
    body = lines[header_row - 1:] if header_row else lines
    rows = [r for r in _csv_reader_rows(body, _csv_delimiter(lines)) if any(c.strip() for c in r)]
    if header_row:
        head, data = rows[0], rows[1:]
    else:
        head, data = [""] * max(len(r) for r in rows), rows
    names: list[str] = []
    for i, h in enumerate(head):
        name = csv_field_name(h, i)
        base, k = name, 2
        while name in names:  # duplicate column names: amount, amount_2 …
            name, k = f"{base}_{k}", k + 1
        names.append(name)
    return names, data, header_row


def csv_rows(text: str) -> list[list[str]]:
    """Rows of a delimited text: delimiter sniffed (, ; tab |), quotes handled."""
    lines = [l for l in text.lstrip("\ufeff").splitlines() if l.strip()]
    return [r for r in _csv_reader_rows(lines) if any(c.strip() for c in r)] if lines else []


def csv_field_name(header: str, i: int) -> str:
    """Column header -> usable field name ('note, with comma' -> 'note_with_comma')."""
    name = re.sub(r"\W+", "_", header.strip()).strip("_")
    if not name:
        return f"column{i + 1}"
    return f"_{name}" if name[0].isdigit() else name


def parse_csv(text: str, header_row: Optional[int] = 1) -> tuple[list[FieldNode], Optional[str]]:
    headers, data, _used = csv_table(text, header_row)
    if not headers:
        raise ValueError("Empty CSV.")
    sample = data[0] if data else []
    out: list[FieldNode] = []
    for i, h in enumerate(headers):
        v = sample[i].strip() if i < len(sample) else ""
        out.append(FieldNode(name=h, path=h, type=_infer_text(v) if v else "string"))
    return out, None


# --------------------------------------------------------------- fixed width
def parse_fixed(text: str) -> tuple[list[FieldNode], Optional[str]]:
    """Fixed-width layout definition (Field / Start / Length / Type) -> flat field tree."""
    from app.services.fixed_width import parse_definition
    return parse_definition(text)[0], None

# --------------------------------------------------------------------- SWIFT
def parse_swift(text: str) -> tuple[list[FieldNode], Optional[str]]:
    """SWIFT MT: every field of the message type in all five blocks (see swift_mt.py). Accepts a
    whole message, or just the type ('MT103', '202COV') to get its field list."""
    from app.services.swift_mt import build_tree
    tree, mt, _note = build_tree(text)
    return tree, mt


# ---------------------------------------------------------------------- POJO
_JAVA_NUMERIC = {"int": "integer", "integer": "integer", "long": "integer", "short": "integer", "byte": "integer",
                 "biginteger": "integer", "double": "number", "float": "number", "bigdecimal": "number",
                 "boolean": "boolean", "string": "string", "char": "string", "character": "string"}
_COLLECTIONS = ("list", "set", "collection", "iterable", "arraylist", "linkedlist", "hashset", "treeset")


def _java_blocks(src: str) -> dict[str, tuple[str, str]]:
    """{type name: ('class' | 'record', body or record parameters)} for every class / record / enum."""
    out: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"\b(class|record|enum|interface)\s+(\w+)\s*(?:<[^>{]*>)?\s*(\(([^)]*)\))?", src):
        kind, name = m.group(1), m.group(2)
        if kind == "record":
            out[name] = ("record", m.group(4) or "")
            continue
        brace = src.find("{", m.end())
        if brace < 0:
            continue
        depth, i = 0, brace
        while i < len(src):
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            if depth == 0:
                break
            i += 1
        out[name] = (kind, src[brace + 1:i])
    return out


def _top_level_statements(body: str) -> list[str]:
    """Statements at the class-body level (nested blocks such as methods are skipped)."""
    stmts, cur, depth = [], "", 0
    for ch in body:
        if ch == "{":
            if depth == 0:
                cur = ""  # a method / nested type body starts: drop its signature
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            continue
        if depth:
            continue
        if ch == ";":
            stmts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return stmts


def parse_pojo(text: str) -> tuple[list[FieldNode], Optional[str]]:
    """Java class(es) or record(s) -> tree. Nested / sibling types become objects, collections and
    arrays become repeating elements, @NotNull / @NonNull fields are mandatory, static fields skipped."""
    src = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    blocks = _java_blocks(src)
    if not blocks:
        raise ValueError("No class or record found.")
    main = next((n for n, _ in blocks.items() if re.search(rf"public\s+(?:final\s+|abstract\s+)*(?:class|record)\s+{n}\b", src)),
                next(iter(blocks)))

    def fields_of(type_name: str) -> list[tuple[str, str, bool]]:
        kind, body = blocks[type_name]
        out = []
        if kind == "record":
            parts = [p.strip() for p in re.split(r",(?![^<]*>)", body) if p.strip()]
            for p in parts:
                mandatory = bool(re.search(r"@(NotNull|NonNull|NotBlank|NotEmpty)\b", p))
                p = re.sub(r"@\w+(\([^)]*\))?", "", p).strip()
                m = re.match(r"(.+?)\s+(\w+)$", p)
                if m:
                    out.append((m.group(1).strip(), m.group(2), mandatory))
            return out
        if kind != "class":
            return out
        for st in _top_level_statements(body):
            mandatory = bool(re.search(r"@(NotNull|NonNull|NotBlank|NotEmpty)\b", st))
            st = re.sub(r"@\w+(\([^)]*\))?", "", st).strip()
            if not st or "(" in st.split("=")[0] or re.search(r"\bstatic\b", st):
                continue
            st = re.sub(r"\b(private|protected|public|final|transient|volatile)\b", "", st).split("=")[0].strip()
            m = re.match(r"(.+?)\s+(\w+)$", st)
            if m and not m.group(1).startswith(("import", "package", "return")):
                out.append((m.group(1).strip(), m.group(2), mandatory))
        return out

    def node_for(jtype: str, name: str, path: str, mandatory: bool, seen: frozenset) -> FieldNode:
        t = re.sub(r"\s+", "", jtype)
        elem = None
        g = re.match(r"(?:[\w.]+\.)?(\w+)<(.+)>$", t)
        if t.endswith("[]"):
            elem = t[:-2]
        elif g and g.group(1).lower() in _COLLECTIONS:
            elem = g.group(2)
        if elem is not None:
            inner = elem.split(".")[-1]
            kids = build(inner, f"{path}[]", seen) if inner in blocks else []
            return FieldNode(name=f"{name}[]", path=f"{path}[]", type="array", mandatory=mandatory, children=kids)
        base = (g.group(1) if g else t).split(".")[-1]
        if base in blocks and blocks[base][0] in ("class", "record") and base not in seen:
            return FieldNode(name=name, path=path, type="object", mandatory=mandatory, children=build(base, path, seen))
        if base.lower() in ("map", "hashmap", "treemap", "linkedhashmap", "object", "jsonnode"):
            return FieldNode(name=name, path=path, type="object", mandatory=mandatory)
        return FieldNode(name=name, path=path, type=_JAVA_NUMERIC.get(base.lower(), norm_type(base) if base[0].islower() else "string"),
                         mandatory=mandatory or base in ("int", "long", "double", "float", "boolean", "short", "byte"))

    def build(type_name: str, prefix: str, seen: frozenset) -> list[FieldNode]:
        seen = seen | {type_name}
        return [node_for(jt, n, f"{prefix}.{n}" if prefix else n, mand, seen) for jt, n, mand in fields_of(type_name)]

    tree = build(main, "", frozenset())
    if not tree:
        raise ValueError(f"No fields found in {main} (expected e.g. private String name;).")
    return tree, main


PARSERS = {
    "jsonschema": parse_json_schema,
    "jsonobject": parse_json_object,
    "xsd": parse_xsd,
    "xml": parse_xml_sample,
    "csv": parse_csv,
    "fixed": parse_fixed,
    "swift": parse_swift,
    "pojo": parse_pojo,
}

FORMAT_LABELS = {"jsonschema": "JSON Schema", "jsonobject": "JSON sample", "xsd": "XSD", "xml": "XML sample",
                 "csv": "CSV", "fixed": "Fixed width", "swift": "SWIFT MT", "pojo": "Java class / POJO"}


def detect_format(text: str) -> Optional[str]:
    """Best guess of what was pasted / uploaded."""
    t = text.strip().lstrip("\ufeff")
    if not t:
        return None
    if t.startswith("<"):
        head = t[:2000]
        return "xsd" if re.search(r"<(\w+:)?schema\b", head) and "XMLSchema" in head else "xml"
    if t.startswith(("{1:", "{2:")) or re.fullmatch(r"(?i)MT\s*\d{3}(\s*COV)?", t) \
            or (re.search(r"^:\d{2}[A-Z]?:", t, re.M) and not t.startswith(("{", "["))):
        return "swift"
    if re.search(r"\b(class|record)\s+\w+", t) and (";" in t or "record" in t) and not t.startswith(("{", "[")):
        return "pojo"
    try:
        obj = _load_structured(t)
    except ValueError:
        obj = None
    if isinstance(obj, dict):
        if "$schema" in obj or isinstance(obj.get("properties"), dict) or "$defs" in obj or "definitions" in obj \
                or (obj.get("type") in ("object", "array") and ("properties" in obj or "items" in obj)):
            return "jsonschema"
        return "jsonobject"
    if isinstance(obj, list):
        return "jsonobject"
    from app.services.fixed_width import looks_like_definition
    if looks_like_definition(t):
        return "fixed"
    first = t.splitlines()[0]
    if any(d in first for d in (",", ";", "\t", "|")):
        return "csv"
    return None


def parse_auto(fmt: str, text: str, csv_header_row: Optional[int] = 1
               ) -> tuple[list[FieldNode], Optional[str], str, Optional[str]]:
    """Parses with the chosen format; when the content is clearly something else (or the chosen
    parser fails and another one works), uses the detected format instead.
    Returns (tree, schema name / namespace, format used, note for the user)."""
    detected = detect_format(text)
    parsers = {**PARSERS, "csv": lambda t: parse_csv(t, csv_header_row)}
    chosen = parsers.get(fmt)
    if not chosen:
        raise ValueError(f"Unknown format: {fmt}")
    # JSON Schema vs sample and XSD vs XML instance are easy to mix up: trust the content.
    if detected and detected != fmt and {fmt, detected} in ({"jsonschema", "jsonobject"}, {"xsd", "xml"}):
        tree, extra = parsers[detected](text)
        return tree, extra, detected, f"Looks like {FORMAT_LABELS[detected]}, not {FORMAT_LABELS[fmt]} — parsed as {FORMAT_LABELS[detected]}."
    try:
        tree, extra = chosen(text)
        note = None
        if fmt == "swift":
            from app.services.swift_mt import build_tree
            note = build_tree(text)[2]
        if fmt == "fixed":
            from app.services.fixed_width import parse_definition
            note = parse_definition(text)[1]
        return tree, extra, fmt, note
    except Exception as first_error:  # noqa: BLE001
        if detected and detected != fmt:
            try:
                tree, extra = parsers[detected](text)
                note = (f"This isn't {FORMAT_LABELS[fmt]} — it looks like {FORMAT_LABELS[detected]}, "
                        f"so it was parsed as {FORMAT_LABELS[detected]}.")
                if detected == "swift":
                    from app.services.swift_mt import build_tree
                    extra_note = build_tree(text)[2]
                    note = f"{note} {extra_note}" if extra_note else note
                return tree, extra, detected, note
            except Exception:  # noqa: BLE001
                pass
        raise


def parse_by_format(fmt: str, text: str) -> tuple[list[FieldNode], Optional[str]]:
    tree, extra, _used, _note = parse_auto(fmt, text)
    return tree, extra


def xsd_target_namespace(text: str) -> Optional[str]:
    """targetNamespace of an XSD whose elements are namespace-qualified."""
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return None
    if _local(root.tag) != "schema":
        return None
    return root.get("targetNamespace") or None


def flatten(tree: list[FieldNode]) -> list[FieldNode]:
    """Depth-first flat list of every node (leaves and containers)."""
    out: list[FieldNode] = []

    def walk(nodes: list[FieldNode]) -> None:
        for n in nodes:
            out.append(n)
            if n.children:
                walk(n.children)

    walk(tree)
    return out

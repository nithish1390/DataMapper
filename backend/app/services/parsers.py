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

SWIFT_TAGS = {
    "13C": "Time Indication", "20": "Transaction Reference", "23B": "Bank Operation Code",
    "23E": "Instruction Code", "26T": "Transaction Type Code",
    "32A": "Value Date Currency Amount", "33B": "Currency Instructed Amount",
    "36": "Exchange Rate", "50A": "Ordering Customer BIC", "50K": "Ordering Customer",
    "52A": "Ordering Institution", "53A": "Sender Correspondent",
    "56A": "Intermediary Institution", "57A": "Account With Institution",
    "59": "Beneficiary Customer", "59A": "Beneficiary Customer BIC",
    "70": "Remittance Information", "71A": "Details of Charges",
    "71F": "Sender Charges", "71G": "Receiver Charges",
    "72": "Sender to Receiver Information", "77B": "Regulatory Reporting",
}


def swift_field_name(tag: str) -> str:
    label = SWIFT_TAGS.get(tag, f"Field_{tag}")
    return re.sub(r"[^A-Za-z0-9]+", "_", label)


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
    obj = json.loads(text)
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
def _infer_from_sample(val: Any) -> str:
    if val is None:
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    if isinstance(val, dict):
        return "object"
    return "string"


def _build_sample_tree(obj: dict, prefix: str, depth: int) -> list[FieldNode]:
    if not obj or depth > 5:
        return []
    out: list[FieldNode] = []
    for key, val in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.append(FieldNode(name=key, path=path, type="object", mandatory=False,
                                  children=_build_sample_tree(val, path, depth + 1)))
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            out.append(FieldNode(name=f"{key}[]", path=f"{path}[]", type="array", mandatory=False,
                                  children=_build_sample_tree(val[0], f"{path}[]", depth + 1)))
        else:
            out.append(FieldNode(name=key, path=path, type=_infer_from_sample(val),
                                  mandatory=False, children=[]))
    return out


def parse_json_object(text: str) -> tuple[list[FieldNode], Optional[str]]:
    obj = json.loads(text)
    tree = _build_sample_tree(obj, "", 0)
    if not tree:
        raise ValueError("Empty object.")
    return tree, None


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
def parse_csv(text: str) -> tuple[list[FieldNode], Optional[str]]:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        raise ValueError("Empty CSV.")
    headers = [h.strip().strip('"') for h in lines[0].split(",")]
    sample_row = lines[1].split(",") if len(lines) > 1 else []
    out: list[FieldNode] = []
    for i, h in enumerate(headers):
        v = sample_row[i].strip() if i < len(sample_row) else ""
        t = "string"
        if v:
            try:
                float(v)
                t = "number" if "." in v else "integer"
            except ValueError:
                pass
        if v.lower() in ("true", "false"):
            t = "boolean"
        out.append(FieldNode(name=h, path=h, type=t, mandatory=False, children=[]))
    return out, None


# ----------------------------------------------------------- Swagger/OpenAPI
def parse_swagger(text: str) -> tuple[list[FieldNode], Optional[str]]:
    obj = json.loads(text)
    bag = (obj.get("components") or {}).get("schemas") or obj.get("definitions") or {}
    if not bag:
        raise ValueError("No components.schemas / definitions found.")
    best_name, best_count = next(iter(bag)), -1
    for name, sub in bag.items():
        count = len((sub or {}).get("properties") or {})
        if count > best_count:
            best_name, best_count = name, count
    chosen = _resolve_schema(obj, bag[best_name], 0)
    tree = _build_schema_tree(chosen.get("properties") or {}, "", 0, obj, chosen.get("required"))
    if not tree:
        raise ValueError(f'Selected schema "{best_name}" has no properties.')
    return tree, best_name


# --------------------------------------------------------------------- SWIFT
def parse_swift(text: str) -> tuple[list[FieldNode], Optional[str]]:
    out: list[FieldNode] = []
    for m in re.finditer(r"^:(\d{2}[A-Z]?):(.*)$", text, re.MULTILINE):
        name = swift_field_name(m.group(1))
        out.append(FieldNode(name=name, path=name, type="string", mandatory=False, children=[]))
    if not out:
        raise ValueError("No :TAG: lines found (e.g. :20:REF12345).")
    return out, None


# ---------------------------------------------------------------------- POJO
def parse_pojo(text: str) -> tuple[list[FieldNode], Optional[str]]:
    out: list[FieldNode] = []
    pattern = r"(?:private|public|protected)\s+(?:static\s+|final\s+)*([\w<>\[\],.\s]+?)\s+(\w+)\s*;"
    for m in re.finditer(pattern, text):
        out.append(FieldNode(name=m.group(2), path=m.group(2), type=norm_type(m.group(1)),
                              mandatory=False, children=[]))
    if not out:
        raise ValueError('No "private Type field;" declarations found.')
    return out, None


PARSERS = {
    "jsonschema": parse_json_schema,
    "jsonobject": parse_json_object,
    "xsd": parse_xsd,
    "csv": parse_csv,
    "swagger": parse_swagger,
    "swift": parse_swift,
    "pojo": parse_pojo,
}


def parse_by_format(fmt: str, text: str) -> tuple[list[FieldNode], Optional[str]]:
    parser = PARSERS.get(fmt)
    if not parser:
        raise ValueError(f"Unknown format: {fmt}")
    return parser(text)


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

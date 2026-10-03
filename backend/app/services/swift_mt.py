"""
SWIFT MT (FIN) support: the complete field tree of a message type, and sample values for Test / Run.

Parsing of the message itself uses the vendored swift-parser-py package (all five blocks; block-4
fields split into named components). The package parses what a message *contains*; the catalogue
below adds what a message type *allows* — every block-4 field of the MT with its options, so that
e.g. MT103 field 50 is offered as a choice of 50A / 50F / 50K, mandatory / optional, repeating, and
the sequences (MT101 sequence B, MT940 statement lines, MT202 COV sequence B).

Tree (names are formula-friendly):
  Block1_Basic_Header          Application_ID, Service_ID, LT_Address, Session_Number, Sequence_Number
  Block2_Application_Header    Input_Output, Message_Type, Receiver_Address, Priority, ... (input + output)
  Block3_User_Header           Tag103_Service_Identifier, ..., Tag121_UETR, ...
  Block4_Text                  F20_Senders_Reference, F32A_Value_Date_Currency_Amount{Date,Currency,Amount},
                               F50A_/F50F_/F50K_Ordering_Customer (choice), F71F_Senders_Charges[], ...
  Block5_Trailer               CHK_Checksum, PDE_Possible_Duplicate_Emission, ...
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.models.schemas import FieldNode

# ------------------------------------------------------------------ catalogue
@dataclass
class F:
    """One block-4 field of a message type."""

    tag: str                 # '50', '32A', '59'
    name: str                # 'Ordering Customer'
    options: list[str] = field(default_factory=lambda: [""])  # ['A', 'F', 'K'] / ['', 'A', 'F'] / ['']
    mandatory: bool = False
    repeating: bool = False


@dataclass
class Seq:
    """A (repeating) sequence: starts at `start`; holds `fields` until a tag outside it appears."""

    name: str
    start: str
    fields: list[F]
    repeating: bool = True
    mandatory: bool = False


def _o(*opts: str) -> list[str]:
    return list(opts)


_PARTY_AD = _o("A", "D")
MT_DEFS: dict[str, dict[str, Any]] = {
    "103": {"title": "Single Customer Credit Transfer", "body": [
        F("20", "Senders Reference", mandatory=True),
        F("13C", "Time Indication", repeating=True),
        F("23B", "Bank Operation Code", mandatory=True),
        F("23E", "Instruction Code", repeating=True),
        F("26T", "Transaction Type Code"),
        F("32A", "Value Date Currency Interbank Settled Amount", mandatory=True),
        F("33B", "Currency Instructed Amount"),
        F("36", "Exchange Rate"),
        F("50", "Ordering Customer", _o("A", "F", "K"), mandatory=True),
        F("51A", "Sending Institution"),
        F("52", "Ordering Institution", _PARTY_AD),
        F("53", "Senders Correspondent", _o("A", "B", "D")),
        F("54", "Receivers Correspondent", _o("A", "B", "D")),
        F("55", "Third Reimbursement Institution", _o("A", "B", "D")),
        F("56", "Intermediary Institution", _o("A", "C", "D")),
        F("57", "Account With Institution", _o("A", "B", "C", "D")),
        F("59", "Beneficiary Customer", _o("", "A", "F"), mandatory=True),
        F("70", "Remittance Information"),
        F("71A", "Details of Charges", mandatory=True),
        F("71F", "Senders Charges", repeating=True),
        F("71G", "Receivers Charges"),
        F("72", "Sender to Receiver Information"),
        F("77B", "Regulatory Reporting"),
        F("77T", "Envelope Contents"),
    ]},
    "101": {"title": "Request for Transfer", "body": [
        Seq("Sequence_A_General_Information", "20", [
            F("20", "Senders Reference", mandatory=True),
            F("21R", "Customer Specified Reference"),
            F("28D", "Message Index Total", mandatory=True),
            F("50", "Instructing Party", _o("C", "L")),
            F("50", "Ordering Customer", _o("F", "G", "H")),
            F("52", "Account Servicing Institution", _o("A", "C")),
            F("51A", "Sending Institution"),
            F("30", "Requested Execution Date", mandatory=True),
            F("25", "Authorisation"),
        ], repeating=False, mandatory=True),
        Seq("Sequence_B_Transaction_Details", "21", [
            F("21", "Transaction Reference", mandatory=True),
            F("21F", "FX Deal Reference"),
            F("23E", "Instruction Code", repeating=True),
            F("32B", "Currency Transaction Amount", mandatory=True),
            F("50", "Instructing Party", _o("C", "L")),
            F("50", "Ordering Customer", _o("F", "G", "H")),
            F("52", "Account Servicing Institution", _o("A", "C")),
            F("56", "Intermediary", _o("A", "C", "D")),
            F("57", "Account With Institution", _o("A", "C", "D")),
            F("59", "Beneficiary", _o("", "A", "F"), mandatory=True),
            F("70", "Remittance Information"),
            F("77B", "Regulatory Reporting"),
            F("33B", "Currency Original Ordered Amount"),
            F("71A", "Details of Charges", mandatory=True),
            F("25A", "Charges Account"),
            F("36", "Exchange Rate"),
        ], mandatory=True),
    ]},
    "202": {"title": "General Financial Institution Transfer", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference", mandatory=True),
        F("13C", "Time Indication", repeating=True),
        F("32A", "Value Date Currency Interbank Settled Amount", mandatory=True),
        F("52", "Ordering Institution", _PARTY_AD),
        F("53", "Senders Correspondent", _o("A", "B", "D")),
        F("54", "Receivers Correspondent", _o("A", "B", "D")),
        F("56", "Intermediary", _PARTY_AD),
        F("57", "Account With Institution", _o("A", "B", "D")),
        F("58", "Beneficiary Institution", _PARTY_AD, mandatory=True),
        F("72", "Sender to Receiver Information"),
    ]},
    "202COV": {"title": "General Financial Institution Transfer (Cover)", "body": [
        Seq("Sequence_A_General_Information", "20", [
            F("20", "Transaction Reference Number", mandatory=True),
            F("21", "Related Reference", mandatory=True),
            F("13C", "Time Indication", repeating=True),
            F("32A", "Value Date Currency Interbank Settled Amount", mandatory=True),
            F("52", "Ordering Institution", _PARTY_AD),
            F("53", "Senders Correspondent", _o("A", "B", "D")),
            F("54", "Receivers Correspondent", _o("A", "B", "D")),
            F("56", "Intermediary", _PARTY_AD),
            F("57", "Account With Institution", _o("A", "B", "D")),
            F("58", "Beneficiary Institution", _PARTY_AD, mandatory=True),
            F("72", "Sender to Receiver Information"),
        ], repeating=False, mandatory=True),
        Seq("Sequence_B_Underlying_Customer_Credit_Transfer", "50", [
            F("50", "Ordering Customer", _o("A", "F", "K"), mandatory=True),
            F("52", "Ordering Institution", _PARTY_AD),
            F("56", "Intermediary Institution", _o("A", "C", "D")),
            F("57", "Account With Institution", _o("A", "B", "C", "D")),
            F("59", "Beneficiary Customer", _o("", "A", "F"), mandatory=True),
            F("70", "Remittance Information"),
            F("72", "Sender to Receiver Information"),
            F("33B", "Currency Instructed Amount"),
        ], repeating=False, mandatory=True),
    ]},
    "199": {"title": "Free Format Message", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference"),
        F("79", "Narrative", mandatory=True),
    ]},
    "299": {"title": "Free Format Message", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference"),
        F("79", "Narrative", mandatory=True),
    ]},
    "900": {"title": "Confirmation of Debit", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference", mandatory=True),
        F("25", "Account Identification", _o("", "P"), mandatory=True),
        F("13D", "Date Time Indication"),
        F("32A", "Value Date Currency Amount", mandatory=True),
        F("52", "Ordering Institution", _PARTY_AD),
        F("72", "Sender to Receiver Information"),
    ]},
    "910": {"title": "Confirmation of Credit", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference", mandatory=True),
        F("25", "Account Identification", _o("", "P"), mandatory=True),
        F("13D", "Date Time Indication"),
        F("32A", "Value Date Currency Amount", mandatory=True),
        F("50", "Ordering Customer", _o("A", "F", "K")),
        F("52", "Ordering Institution", _PARTY_AD),
        F("56", "Intermediary", _PARTY_AD),
        F("72", "Sender to Receiver Information"),
    ]},
    "940": {"title": "Customer Statement Message", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("21", "Related Reference"),
        F("25", "Account Identification", _o("", "P"), mandatory=True),
        F("28C", "Statement Number Sequence Number", mandatory=True),
        F("60", "Opening Balance", _o("F", "M"), mandatory=True),
        Seq("Statement_Line", "61", [
            F("61", "Statement Line", mandatory=True),
            F("86", "Information to Account Owner"),
        ]),
        F("62", "Closing Balance", _o("F", "M"), mandatory=True),
        F("64", "Closing Available Balance"),
        F("65", "Forward Available Balance", repeating=True),
        F("86", "Information to Account Owner"),
    ]},
    "950": {"title": "Statement Message", "body": [
        F("20", "Transaction Reference Number", mandatory=True),
        F("25", "Account Identification", mandatory=True),
        F("28C", "Statement Number Sequence Number", mandatory=True),
        F("60", "Opening Balance", _o("F", "M"), mandatory=True),
        F("61", "Statement Line", repeating=True),
        F("62", "Closing Balance", _o("F", "M"), mandatory=True),
        F("64", "Closing Available Balance"),
    ]},
}

BLOCK1 = [("Application_ID", True), ("Service_ID", True), ("LT_Address", True),
          ("Session_Number", True), ("Sequence_Number", True)]
BLOCK2 = [("Input_Output", True), ("Message_Type", True),
          ("Receiver_Address", False), ("Priority", False), ("Delivery_Monitoring", False), ("Obsolescence_Period", False),
          ("Input_Time", False), ("Input_Date", False), ("Sender_LT_Address", False), ("Session_Number", False),
          ("Sequence_Number", False), ("Output_Date", False), ("Output_Time", False)]
BLOCK3 = {"103": "Service_Identifier", "113": "Banking_Priority", "108": "Message_User_Reference",
          "119": "Validation_Flag", "423": "Balance_Checkpoint", "106": "Message_Input_Reference",
          "424": "Related_Reference", "111": "Service_Type_Identifier", "121": "UETR",
          "115": "Addressee_Information", "165": "Payment_Release_Information",
          "433": "Sanctions_Screening_Information", "434": "Payment_Controls_Information"}
BLOCK5 = {"CHK": "Checksum", "TNG": "Test_And_Training", "PDE": "Possible_Duplicate_Emission",
          "PDM": "Possible_Duplicate_Message", "DLM": "Delayed_Message", "MRF": "Message_Reference",
          "SYS": "System_Originated_Message", "MAC": "Authentication_Code", "PAC": "Proprietary_Authentication_Code"}

_PATTERNS: Optional[dict] = None


# Field formats missing from the package's catalogue (SWIFT user handbook formats).
_EXTRA_PATTERNS = {
    "50G": {"pattern": "/34x$4!a2!a2!c[3!c]", "fieldNames": "(Account)$(BIC)"},
    "50H": {"pattern": "/34x$4*35x", "fieldNames": "(Account)$(Name and Address)"},
    "25P": {"pattern": "35x$4!a2!a2!c[3!c]", "fieldNames": "(Account)$(BIC)"},
    "13D": {"pattern": "6!n4!n1!x4!n", "fieldNames": "(Date)(Time)(Sign)(Offset)"},
}
_AMOUNT_PARTS = {"Amount", "Instructed_Amount", "Rate"}


def _package_patterns() -> set:
    p = Path(__file__).resolve().parent.parent / "vendor" / "swift_parser_py" / "metadata" / "patterns.json"
    try:
        return set(json.loads(p.read_text()))
    except OSError:
        return set()


def _patterns() -> dict:
    global _PATTERNS
    if _PATTERNS is None:
        p = Path(__file__).resolve().parent.parent / "vendor" / "swift_parser_py" / "metadata" / "patterns.json"
        try:
            _PATTERNS = json.loads(p.read_text())
        except OSError:
            _PATTERNS = {}
        for k, v in _EXTRA_PATTERNS.items():
            _PATTERNS.setdefault(k, v)
    return _PATTERNS


def _ident(text: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", text.strip())
    return "_".join(w[:1].upper() + w[1:] for w in words if w)


def field_name(tag: str, option: str, name: str) -> str:
    """('50', 'K', 'Ordering Customer') -> 'F50K_Ordering_Customer'."""
    return f"F{tag}{option}_{_ident(name)}"


def components(tag_option: str) -> list[tuple[str, bool]]:
    """[(component name, repeating lines)] from the package's field patterns."""
    pat = _patterns().get(tag_option)
    if not pat:
        return []
    names = re.findall(r"\(([^)]*)\)", pat.get("fieldNames", ""))
    name_segments = pat.get("fieldNames", "").split("$")
    pat_segments = pat.get("pattern", "").split("$")
    out: list[tuple[str, bool]] = []
    for i, seg in enumerate(name_segments):
        seg_names = re.findall(r"\(([^)]*)\)", seg)
        multi = i < len(pat_segments) and bool(re.search(r"\d\*\d", pat_segments[i]))
        for n in seg_names:
            out.append((_ident(n), multi and len(seg_names) == 1))
    # a single plain component is just the field's value (a leaf); otherwise expose the components
    return out if len(out) > 1 or any(multi for _n, multi in out) else []


def _field_nodes(f: F, prefix: str, group: str) -> list[FieldNode]:
    nodes = []
    choice = f"{group}#F{f.tag}{''.join(f.options)}" if len(f.options) > 1 else None
    for opt in f.options:
        nm = field_name(f.tag, opt, f.name)
        path = f"{prefix}.{nm}" + ("[]" if f.repeating else "")
        comps = components(f.tag + opt)
        kids = [FieldNode(name="Value", path=f"{path}.Value", type="string")] if comps else []
        for cname, multi in comps:
            kids.append(FieldNode(name=f"{cname}[]" if multi else cname,
                                  path=f"{path}.{cname}" + ("[]" if multi else ""),
                                  type="array" if multi else ("number" if cname in _AMOUNT_PARTS else "string")))
        node_type = "array" if f.repeating else ("object" if kids else "string")
        nodes.append(FieldNode(name=nm + ("[]" if f.repeating else ""), path=path, type=node_type,
                               mandatory=f.mandatory and not choice, children=kids, choice=choice))
    return nodes


def _body_nodes(body: list, prefix: str) -> list[FieldNode]:
    out: list[FieldNode] = []
    for item in body:
        if isinstance(item, Seq):
            path = f"{prefix}.{item.name}" + ("[]" if item.repeating else "")
            out.append(FieldNode(name=item.name + ("[]" if item.repeating else ""), path=path,
                                 type="array" if item.repeating else "object", mandatory=item.mandatory,
                                 children=_body_nodes(item.fields, path)))
        else:
            out.extend(_field_nodes(item, prefix, prefix))
    return out


# ------------------------------------------------------------------ parsing
def _parse_raw(text: str) -> dict:
    from app.vendor.swift_parser_py.swift_parser import SwiftParser

    result: dict = {}

    def cb(err, res):
        result["err"], result["res"] = err, res

    try:
        SwiftParser().parse(text.strip(), cb)
    except Exception as exc:  # noqa: BLE001
        result["err"] = exc
    return result.get("res") or {}


def message_type(text: str) -> Optional[str]:
    t = text.strip()
    m = re.fullmatch(r"(?:MT\s*)?(\d{3})(\s*COV)?", t, re.I)
    if m:
        return m.group(1) + ("COV" if m.group(2) else "")
    b2 = re.search(r"\{2:[IO](\d{3})", t)
    if not b2:
        return None
    mt = b2.group(1)
    if mt == "202" and re.search(r"\{119:COV\}", t):
        mt = "202COV"
    return mt


def _present_fields(text: str) -> list[F]:
    """Block-4 fields present in a message (for message types outside the catalogue)."""
    seen: dict[str, F] = {}
    for m in re.finditer(r"^:(\d{2})([A-Z]?):", text, re.M):
        tag, opt = m.group(1), m.group(2)
        key = tag + opt
        if key in seen:
            seen[key].repeating = True
        else:
            seen[key] = F(key, f"Field {key}")
    return list(seen.values())


def build_tree(text: str) -> tuple[list[FieldNode], str, Optional[str]]:
    """(tree of all five blocks for the message type, 'MT103', note). `text` may be a whole message or
    just a type such as 'MT103' / '202COV'."""
    mt = message_type(text)
    if not mt:
        raise ValueError("Not a SWIFT MT message: no {2:...} application header (or type like MT103) found.")
    definition = MT_DEFS.get(mt)
    note = None
    if definition:
        body = definition["body"]
    else:
        body = _present_fields(text)
        note = f"MT{mt} is not in the field catalogue — showing the fields present in the message."
    b1 = FieldNode(name="Block1_Basic_Header", path="Block1_Basic_Header", type="object", mandatory=True,
                   children=[FieldNode(name=n, path=f"Block1_Basic_Header.{n}", type="string", mandatory=m) for n, m in BLOCK1])
    b2 = FieldNode(name="Block2_Application_Header", path="Block2_Application_Header", type="object", mandatory=True,
                   children=[FieldNode(name=n, path=f"Block2_Application_Header.{n}", type="string", mandatory=m) for n, m in BLOCK2])
    b3 = FieldNode(name="Block3_User_Header", path="Block3_User_Header", type="object",
                   children=[FieldNode(name=f"Tag{t}_{n}", path=f"Block3_User_Header.Tag{t}_{n}", type="string")
                             for t, n in BLOCK3.items()])
    b4 = FieldNode(name="Block4_Text", path="Block4_Text", type="object", mandatory=True,
                   children=_body_nodes(body, "Block4_Text"))
    b5 = FieldNode(name="Block5_Trailer", path="Block5_Trailer", type="object",
                   children=[FieldNode(name=f"{t}_{n}", path=f"Block5_Trailer.{t}_{n}", type="string")
                             for t, n in BLOCK5.items()])
    return [b1, b2, b3, b4, b5], f"MT{mt}", note


# ------------------------------------------------------------------ values
def _blocks12(text: str) -> tuple[dict, dict]:
    b1: dict = {}
    m = re.search(r"\{1:([A-Z])(\d{2})([A-Z0-9]{12})(\d{4})(\d{6})", text)
    if m:
        b1 = dict(zip([n for n, _ in BLOCK1], m.groups()))
    b2: dict = {}
    m = re.search(r"\{2:I(\d{3})([A-Z0-9]{12})([SUN])?(\d)?(\d{3})?", text)
    if m:
        b2 = {"Input_Output": "I", "Message_Type": m.group(1), "Receiver_Address": m.group(2),
              "Priority": m.group(3), "Delivery_Monitoring": m.group(4), "Obsolescence_Period": m.group(5)}
    m = re.search(r"\{2:O(\d{3})(\d{4})(\d{6})([A-Z0-9]{12})(\d{4})(\d{6})(\d{6})(\d{4})([SUN])?", text)
    if m:
        b2 = {"Input_Output": "O", "Message_Type": m.group(1), "Input_Time": m.group(2), "Input_Date": m.group(3),
              "Sender_LT_Address": m.group(4), "Session_Number": m.group(5), "Sequence_Number": m.group(6),
              "Output_Date": m.group(7), "Output_Time": m.group(8), "Priority": m.group(9)}
    return b1, {k: v for k, v in b2.items() if v is not None}


def _swift_decimal(v: Any) -> Any:
    """SWIFT amounts use a decimal comma: '1234,56' -> '1234.56' (the raw text stays in Value)."""
    return v.replace(",", ".") if isinstance(v, str) and re.fullmatch(r"\d+,\d*", v) else v


def _split_lines(tag_option: str, value: str) -> dict:
    """Components for the extra patterns: '$' separates lines; the last part takes the remaining lines."""
    pat = _EXTRA_PATTERNS.get(tag_option)
    if not pat:
        return {}
    names = [_ident(n) for n in re.findall(r"\(([^)]*)\)", pat["fieldNames"])]
    lines = value.split("\n")
    if "$" not in pat["pattern"]:
        return {}
    out = {names[0]: lines[0]}
    if len(names) > 1:
        out[names[1]] = lines[1:]
    return out


def _field_value(tag_option: str, value: str, ast: Optional[dict]) -> Any:
    comps = components(tag_option)
    if not comps:
        return value
    out: dict = {"Value": value}
    if tag_option in _EXTRA_PATTERNS and tag_option not in _package_patterns():
        by_ident = _split_lines(tag_option, value)  # the package has no format for it
    else:
        by_ident = {_ident(k): v for k, v in (ast or {}).items()}
    for cname, multi in comps:
        v = by_ident.get(cname)
        if v is None:
            continue
        if multi:
            out[cname] = v if isinstance(v, list) else [v]
        else:
            v = "\n".join(v) if isinstance(v, list) else v
            out[cname] = _swift_decimal(v) if cname in _AMOUNT_PARTS else v
    return out


def _lookup(body: list, tag: str, option: str) -> Optional[tuple[str, bool]]:
    """(node name, repeating) for a tag+option in a list of catalogue fields."""
    for item in body:
        if isinstance(item, F):
            if item.tag == tag and option in item.options:
                return field_name(item.tag, option, item.name), item.repeating
            if item.tag == tag + option and item.options == [""]:
                return field_name(item.tag, "", item.name), item.repeating
    return None


def extract_values(text: str) -> dict:
    """A message's values shaped exactly like build_tree() (for Test / Run)."""
    res = _parse_raw(text)
    mt = message_type(text) or ""
    definition = MT_DEFS.get(mt)
    body = definition["body"] if definition else _present_fields(text)
    b1, b2 = _blocks12(text)
    b3: dict = {}
    for key, val in res.items():
        m = re.fullmatch(r"block(\d{3})", key)
        if m and m.group(1) in BLOCK3:
            content = val.get("content") if isinstance(val, dict) else val
            b3[f"Tag{m.group(1)}_{BLOCK3[m.group(1)]}"] = content[0] if isinstance(content, list) and content else content
    b5: dict = {}
    for k, v in ((res.get("block5") or {}).get("tags") or {}).items():
        if k in BLOCK5:
            b5[f"{k}_{BLOCK5[k]}"] = v

    b4: dict = {}
    current: dict = b4
    open_seq: Optional[Seq] = None
    seqs = [s for s in body if isinstance(s, Seq)]
    top_fields = [f for f in body if isinstance(f, F)]
    for fld in (res.get("block4") or {}).get("fields") or []:
        tag, opt = str(fld.get("type", "")), str(fld.get("option", ""))
        starts = next((s for s in seqs if s.start == tag), None)
        if starts and (starts is not open_seq or starts.repeating):
            # a sequence starts (or a repeating one starts its next occurrence)
            if starts.repeating:
                current = {}
                b4.setdefault(starts.name, []).append(current)
            else:
                current = b4.setdefault(starts.name, {})
            open_seq = starts
        elif open_seq and not _lookup(open_seq.fields, tag, opt):
            current, open_seq = b4, None  # a field outside the sequence closes it
        scope = open_seq.fields if open_seq else top_fields
        name, repeating = _lookup(scope, tag, opt) or (field_name(tag + opt, "", f"Field {tag}{opt}"), False)
        raw = re.sub(r"^:\d{2}[A-Z]?:", "", str(fld.get("content") or "")) or str(fld.get("fieldValue", ""))
        if raw.startswith(":") and f":{tag}{opt}:{raw}" not in text and f":{tag}{opt}:{raw[1:]}" in text:
            raw = raw[1:]  # the package keeps an extra ':' on some fields (e.g. the first :61:)
        v = _field_value(tag + opt, raw.rstrip("\n"), fld.get("ast"))
        if repeating or name in current:
            prev = current.get(name)
            current[name] = (prev if isinstance(prev, list) else ([prev] if prev is not None else [])) + [v]
        else:
            current[name] = v
    return {"Block1_Basic_Header": b1, "Block2_Application_Header": b2, "Block3_User_Header": b3,
            "Block4_Text": b4, "Block5_Trailer": b5}


def choice_defaults(text: str, tree: list[FieldNode]) -> dict[str, str]:
    """For each choice (50A / 50F / 50K …), the alternative the message actually contains."""
    present = {m.group(1) + m.group(2) for m in re.finditer(r"^:(\d{2})([A-Z]?):", text, re.M)}
    out: dict[str, str] = {}

    def walk(nodes: list[FieldNode]) -> None:
        for n in nodes:
            m = re.match(r"F(\d{2}[A-Z]?)_", n.name)
            if n.choice and m and m.group(1) in present and n.choice not in out:
                out[n.choice] = n.path
            walk(n.children)

    walk(tree)
    return out


# ------------------------------------------------------------------ writing
# A SWIFT target is produced as XML shaped like the tree (wrapped in <SwiftMessage>) and then written
# as MT text. The same rules exist twice: in Python (Test / Run processor) and as XSLT templates (so
# the generated XSLT itself outputs the MT message). Both are driven by field_spec() below.
WRAPPER = "SwiftMessage"
_TOKEN = re.compile(r"(\[)?(/{0,2})(\d+(?:!|\*\d+)?[a-z])\]?")
_FIELD_EL = re.compile(r"F(\d{2}[A-Z]?)_")


@dataclass
class Part:
    name: str
    prefix: str = ""      # '/' or '//' written before a non-empty value that lacks it
    multi: bool = False   # repeating lines
    amount: bool = False  # decimal comma


def field_spec(tag_option: str) -> list[list[Part]]:
    """Lines (segments) of a composite field and their parts, from the field pattern."""
    comps = components(tag_option)
    pat = _patterns().get(tag_option) or {}
    if not comps:
        return []
    multi = dict(comps)
    name_segs = pat.get("fieldNames", "").split("$")
    pat_segs = pat.get("pattern", "").split("$")
    if len(name_segs) != len(pat_segs):
        name_segs, pat_segs = ["".join(name_segs)], ["".join(pat_segs)]
    out: list[list[Part]] = []
    for nseg, pseg in zip(name_segs, pat_segs):
        names = [_ident(n) for n in re.findall(r"\(([^)]*)\)", nseg)]
        tokens = _TOKEN.findall(pseg)
        seg = []
        for i, n in enumerate(names):
            tok = tokens[i] if len(tokens) == len(names) else (tokens[0] if i == 0 and tokens else None)
            seg.append(Part(n, prefix=tok[1] if tok else "", multi=multi.get(n, False),
                            amount=n in _AMOUNT_PARTS or bool(tok and tok[2].endswith("d") and len(tokens) == len(names))))
        # The account goes on its own line before the BIC (options A / B / D …); the patterns omit that '$'.
        k = next((i for i, p in enumerate(seg) if p.name == "BIC"), 0)
        if k and seg[k - 1].name == "Account":
            out += [seg[:k], seg[k:]]
        else:
            out.append(seg)
    if tag_option == "61":  # [//16x] reference of the servicing institution, then details on the next line
        flat = [p for s in out for p in s]
        for p in flat:
            if p.name == "Account_Owner_Reference":
                p.prefix = "//"
        out = [[p for p in flat if p.name != "Supplementary_Details"],
               [p for p in flat if p.name == "Supplementary_Details"]]
    return out


_TREE_MT: dict[tuple, str] = {}


def tree_message_type(fields: list[FieldNode]) -> str:
    """'103' / '202COV' … for a target tree built by build_tree() (by its block-4 field names)."""
    b4 = next((n for n in fields if n.name == "Block4_Text"), None)
    if b4 is None:
        return ""
    key = tuple(c.name for c in b4.children)
    if not _TREE_MT:
        for mt in MT_DEFS:
            _TREE_MT[tuple(c.name for c in build_tree(mt)[0][3].children)] = mt
    return _TREE_MT.get(key, "")


def composite_fields(fields: list[FieldNode]) -> dict[str, str]:
    """Element name -> tag+option for every composite block-4 field of the tree."""
    out: dict[str, str] = {}

    def walk(nodes: list[FieldNode]) -> None:
        for n in nodes:
            m = _FIELD_EL.match(n.name)
            if m and any(c.name == "Value" for c in n.children):
                out[n.name.removesuffix("[]")] = m.group(1)
            else:
                walk(n.children)

    walk(next((n.children for n in fields if n.name == "Block4_Text"), []))
    return out


# ---- Python writer (from the XML the mapping produced)
def _norm(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _txt(el) -> str:
    return (el.text or "") if el is not None else ""


def _amount(v: str) -> str:
    return v.replace(".", ",") + ("" if "," in v or "." in v else ",")


def _write_field(el, tag: str) -> str:
    if not _norm(el):
        return ""
    value = el.find("Value")
    spec = field_spec(tag)
    if not spec or _norm(value) or not len(el):
        body = _txt(value) if _norm(value) else _txt(el)
    else:
        lines = []
        for seg in spec:
            if not any(_norm(c) for p in seg for c in el.findall(p.name)):
                continue
            line = ""
            for p in seg:
                kids = [c for c in el.findall(p.name) if _norm(c)] if p.multi else el.findall(p.name)[:1]
                if p.multi:
                    line += "\n".join(_txt(c) for c in kids)
                    continue
                v = _txt(kids[0]) if kids else ""
                if p.prefix and _norm(kids[0] if kids else None) and not v.startswith(p.prefix):
                    line += p.prefix
                line += _amount(v) if p.amount and _norm(kids[0] if kids else None) else v
            lines.append(line)
        body = "\n".join(lines)
    return f":{tag}:{body}\n"


def _write_block4(el) -> str:
    out = ""
    for c in el:
        m = _FIELD_EL.match(c.tag)
        out += _write_field(c, m.group(1)) if m else _write_block4(c)
    return out


def _or(el, name: str, default: str = "") -> str:
    c = el.find(name) if el is not None else None
    return _txt(c) if _norm(c) else default


def write_mt(xml_text: str, mt: str) -> str:
    """MT text from the <SwiftMessage> XML of a SWIFT target."""
    from lxml import etree

    root = etree.fromstring(xml_text.encode("utf-8"))
    if root.tag != WRAPPER:
        return xml_text
    b1, b2, b3, b4, b5 = (root.find(n) for n in ("Block1_Basic_Header", "Block2_Application_Header",
                                                 "Block3_User_Header", "Block4_Text", "Block5_Trailer"))
    out = "{1:" + _or(b1, "Application_ID", "F") + _or(b1, "Service_ID", "01") + _or(b1, "LT_Address") \
        + _or(b1, "Session_Number", "0000") + _or(b1, "Sequence_Number", "000000") + "}"
    mtype = _or(b2, "Message_Type", mt[:3])
    if _or(b2, "Input_Output") == "O":
        out += "{2:O" + mtype + "".join(_or(b2, n) for n in ("Input_Time", "Input_Date", "Sender_LT_Address",
                                        "Session_Number", "Sequence_Number", "Output_Date", "Output_Time", "Priority")) + "}"
    else:
        out += "{2:I" + mtype + "".join(_or(b2, n) for n in ("Receiver_Address", "Priority", "Delivery_Monitoring",
                                                              "Obsolescence_Period")) + "}"
    tags3 = "".join("{" + c.tag[3:6] + ":" + _txt(c) + "}" for c in (b3 if b3 is not None else []) if _norm(c))
    if mt == "202COV" and "{119:" not in tags3:
        tags3 = "{119:COV}" + tags3
    if tags3:
        out += "{3:" + tags3 + "}"
    out += "{4:\n" + (_write_block4(b4) if b4 is not None else "") + "-}"
    tags5 = "".join("{" + c.tag.split("_")[0] + ":" + _txt(c) + "}" for c in (b5 if b5 is not None else []) if _norm(c))
    if tags5:
        out += "{5:" + tags5 + "}"
    return out


# ---- XSLT writer (templates in mode "mt")
def _x_or(path: str, default: str) -> str:
    if not default:
        return f'<xsl:value-of select="{path}"/>'
    return (f'<xsl:choose><xsl:when test="normalize-space({path})"><xsl:value-of select="{path}"/></xsl:when>'
            f"<xsl:otherwise>{default}</xsl:otherwise></xsl:choose>")


def _x_field(name: str, tag: str) -> list[str]:
    any_of = lambda seg: " or ".join(f"{p.name}[normalize-space()]" for p in seg)  # noqa: E731
    lines = [f'  <xsl:template match="{name}" mode="mt-field" priority="2">',
             '    <xsl:if test="normalize-space(.)">',
             f"      <xsl:text>:{tag}:</xsl:text>",
             '      <xsl:choose><xsl:when test="normalize-space(Value)"><xsl:value-of select="Value"/></xsl:when>',
             "      <xsl:otherwise>"]
    spec = field_spec(tag)
    for i, seg in enumerate(spec):
        lines.append(f'        <xsl:if test="{any_of(seg)}">')
        if i:
            prev = " or ".join(f"({any_of(s)})" for s in spec[:i])
            lines.append(f'          <xsl:if test="{prev}"><xsl:text>&#10;</xsl:text></xsl:if>')
        for p in seg:
            if p.multi:
                lines.append(f'          <xsl:for-each select="{p.name}[normalize-space()]"><xsl:if test="position() &gt; 1">'
                             '<xsl:text>&#10;</xsl:text></xsl:if><xsl:value-of select="."/></xsl:for-each>')
                continue
            v = f"{p.name}[1]"
            if p.prefix:
                lines.append(f'          <xsl:if test="normalize-space({v}) and not(starts-with({v}, \'{p.prefix}\'))">'
                             f"<xsl:text>{p.prefix}</xsl:text></xsl:if>")
            if p.amount:
                lines.append(f'          <xsl:value-of select="translate({v}, \'.\', \',\')"/><xsl:if test="normalize-space({v}) '
                             f'and not(contains({v}, \'.\')) and not(contains({v}, \',\'))">,</xsl:if>')
            else:
                lines.append(f'          <xsl:value-of select="{v}"/>')
        lines.append("        </xsl:if>")
    lines += ["      </xsl:otherwise></xsl:choose>",
              "      <xsl:text>&#10;</xsl:text>",
              "    </xsl:if>",
              "  </xsl:template>"]
    return lines


def xslt_templates(fields: list[FieldNode], mt: str) -> list[str]:
    b1, b2 = "Block1_Basic_Header/", "Block2_Application_Header/"
    out = [
        "  <!-- SWIFT MT output: the message built above is written as MT text -->",
        f'  <xsl:template match="{WRAPPER}" mode="mt">',
        "    <xsl:text>{1:</xsl:text>" + _x_or(b1 + "Application_ID", "F") + _x_or(b1 + "Service_ID", "01")
        + _x_or(b1 + "LT_Address", "") + _x_or(b1 + "Session_Number", "0000")
        + _x_or(b1 + "Sequence_Number", "000000") + "<xsl:text>}</xsl:text>",
        f'    <xsl:choose><xsl:when test="{b2}Input_Output = \'O\'"><xsl:text>{{2:O</xsl:text>'
        + _x_or(b2 + "Message_Type", mt[:3])
        + "".join(_x_or(b2 + n, "") for n in ("Input_Time", "Input_Date", "Sender_LT_Address", "Session_Number",
                                              "Sequence_Number", "Output_Date", "Output_Time", "Priority"))
        + "<xsl:text>}</xsl:text></xsl:when>",
        "      <xsl:otherwise><xsl:text>{2:I</xsl:text>" + _x_or(b2 + "Message_Type", mt[:3])
        + "".join(_x_or(b2 + n, "") for n in ("Receiver_Address", "Priority", "Delivery_Monitoring", "Obsolescence_Period"))
        + "<xsl:text>}</xsl:text></xsl:otherwise></xsl:choose>",
    ]
    b3 = "Block3_User_Header/*[normalize-space()]"
    cov = ' or not(Block3_User_Header/Tag119_Validation_Flag[normalize-space()])' if mt == "202COV" else ""
    out += [
        f'    <xsl:if test="{b3}{cov}"><xsl:text>{{3:</xsl:text>',
        *(['      <xsl:if test="not(Block3_User_Header/Tag119_Validation_Flag[normalize-space()])">'
           "<xsl:text>{119:COV}</xsl:text></xsl:if>"] if cov else []),
        f'      <xsl:for-each select="{b3}"><xsl:text>{{</xsl:text><xsl:value-of select="substring(local-name(), 4, 3)"/>'
        '<xsl:text>:</xsl:text><xsl:value-of select="."/><xsl:text>}</xsl:text></xsl:for-each>',
        "      <xsl:text>}</xsl:text></xsl:if>",
        "    <xsl:text>{4:&#10;</xsl:text>",
        '    <xsl:apply-templates select="Block4_Text/*" mode="mt-field"/>',
        "    <xsl:text>-}</xsl:text>",
        '    <xsl:if test="Block5_Trailer/*[normalize-space()]"><xsl:text>{5:</xsl:text>',
        '      <xsl:for-each select="Block5_Trailer/*[normalize-space()]"><xsl:text>{</xsl:text>'
        "<xsl:value-of select=\"substring-before(local-name(), '_')\"/><xsl:text>:</xsl:text>"
        '<xsl:value-of select="."/><xsl:text>}</xsl:text></xsl:for-each>',
        "      <xsl:text>}</xsl:text></xsl:if>",
        "  </xsl:template>",
        "  <!-- a block-4 field: :tag:value -->",
        "  <xsl:template match=\"*[starts-with(local-name(), 'F') and contains(local-name(), '_') and "
        "translate(substring(local-name(), 2, 2), '0123456789', '') = '']\" mode=\"mt-field\" priority=\"1\">",
        '    <xsl:if test="normalize-space(.)">',
        "      <xsl:text>:</xsl:text><xsl:value-of select=\"substring-before(substring(local-name(), 2), '_')\"/>"
        "<xsl:text>:</xsl:text>",
        '      <xsl:choose><xsl:when test="normalize-space(Value)"><xsl:value-of select="Value"/></xsl:when>'
        '<xsl:otherwise><xsl:value-of select="."/></xsl:otherwise></xsl:choose>',
        "      <xsl:text>&#10;</xsl:text>",
        "    </xsl:if>",
        "  </xsl:template>",
        "  <!-- a sequence: its fields in order -->",
        '  <xsl:template match="*" mode="mt-field"><xsl:apply-templates select="*" mode="mt-field"/></xsl:template>',
    ]
    for name, tag in composite_fields(fields).items():
        out += _x_field(name, tag)
    return out

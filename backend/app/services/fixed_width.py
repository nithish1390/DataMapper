"""
Fixed-width (positional) records.

The source / target is described by a layout definition, uploaded or pasted, e.g.

    Field       Start   Length   Type
    -----------------------------------
    AccountNo   1       10       String
    Name        11      15       String
    Amount      26      11       Decimal
    Currency    37      3        String

Columns may be separated by spaces, tabs, '|', ',' or ';' (an Excel definition arrives as CSV). The header
line is optional (default order: Field, Start, Length, Type); 'End' may replace 'Length', and a
'Mandatory' / 'Required' column (Y / N) is honoured. Starts are 1-based (0-based layouts are detected).

Reading: each field is cut from the first data line of the sample and trimmed; numbers lose their
leading zeros. Writing (target): fields in start order; text is left-aligned and padded with spaces,
numbers are right-aligned and padded with zeros (a '-' stays in front); empty fields are spaces; too
long values are cut to the field length; gaps between fields are spaces. The same writer exists in
Python (processor engine) and as XSLT templates (generated XSLT), so both give the same record.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.schemas import FieldNode

WRAPPER = "Record"

_TYPES = {
    "string": "string", "str": "string", "text": "string", "char": "string", "character": "string",
    "alpha": "string", "alphanumeric": "string", "an": "string", "x": "string", "varchar": "string",
    "date": "string", "datetime": "string", "time": "string",
    "decimal": "number", "number": "number", "numeric": "number", "amount": "number", "float": "number",
    "double": "number", "money": "number", "currencyamount": "number", "bigdecimal": "number",
    "integer": "integer", "int": "integer", "long": "integer", "short": "integer", "n": "integer",
    "digits": "integer", "biginteger": "integer",
    "boolean": "boolean", "bool": "boolean", "flag": "boolean",
}
_HEAD = {
    "name": ("field", "fieldname", "name", "column", "element", "fieldid"),
    "start": ("start", "startpos", "startposition", "position", "pos", "from", "offset", "begin"),
    "length": ("length", "len", "size", "width"),
    "end": ("end", "endpos", "endposition", "to"),
    "type": ("type", "datatype", "format", "fieldtype"),
    "mandatory": ("mandatory", "required", "req", "m"),
}


def _key(cell: str) -> Optional[str]:
    c = re.sub(r"[^a-z]", "", cell.lower())
    return next((k for k, names in _HEAD.items() if c in names), None)


def _split(line: str, ncols: int) -> list[str]:
    for d in ("|", "\t", ";", ","):
        if d in line:
            cells = [c.strip() for c in line.split(d)]
            if d == "|":
                cells = [c for c in cells if c != ""] if line.strip().startswith("|") else cells
            return cells
    tokens = line.split()
    if ncols and len(tokens) > ncols:  # a name with spaces: the extra leading tokens belong to it
        extra = len(tokens) - ncols
        tokens = [" ".join(tokens[: extra + 1])] + tokens[extra + 1:]
    return tokens


def looks_like_definition(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()][:5]
    return any(re.search(r"(?i)\bstart\b", l) and re.search(r"(?i)\b(length|len|end)\b", l) for l in lines)


def parse_definition(text: str) -> tuple[list[FieldNode], str]:
    """(flat field tree with start / length, note)."""
    lines = [l for l in text.lstrip("﻿").splitlines() if l.strip() and not re.fullmatch(r"[\s\-=+|_:]+", l)]
    if not lines:
        raise ValueError("Empty definition. Paste lines like:  AccountNo  1  10  String")
    cols: list[Optional[str]] = ["name", "start", "length", "type"]
    first = _split(lines[0], 0)
    if sum(1 for c in first if _key(c)) >= 2 and not any(re.fullmatch(r"\d+", c) for c in first):
        cols = [_key(c) for c in first]
        lines = lines[1:]
        if "start" not in cols or not ({"length", "end"} & set(cols)):
            raise ValueError("The definition header needs a Start column and a Length (or End) column.")
        if "name" not in cols:
            cols[0] = "name"
    rows: list[dict] = []
    for n, line in enumerate(lines, 1):
        cells = _split(line, len(cols))
        row = {c: cells[i] for i, c in enumerate(cols) if c and i < len(cells)}
        try:
            start = int(row.get("start", ""))
            length = int(row["length"]) if row.get("length") else int(row.get("end", "")) - start + 1
        except ValueError:
            raise ValueError(f"Definition line {n} ('{line.strip()}'): Start and Length must be numbers.") from None
        if length <= 0:
            raise ValueError(f"Definition line {n} ('{line.strip()}'): the length must be at least 1.")
        rows.append({**row, "start": start, "length": length})
    if not rows:
        raise ValueError("The definition has a header but no fields.")
    notes: list[str] = []
    if min(r["start"] for r in rows) == 0:  # 0-based offsets
        for r in rows:
            r["start"] += 1
        notes.append("Starts are 0-based offsets; shown 1-based.")
    nodes: list[FieldNode] = []
    names: set[str] = set()
    for i, r in enumerate(rows):
        name = re.sub(r"\W+", "_", (r.get("name") or "").strip()).strip("_") or f"field{i + 1}"
        if name[0].isdigit():
            name = "_" + name
        base, k = name, 2
        while name in names:
            name, k = f"{base}_{k}", k + 1
        names.add(name)
        typ = _TYPES.get(re.sub(r"[^a-z]", "", (r.get("type") or "string").lower()), "string")
        mand = (r.get("mandatory") or "").strip().lower() in ("y", "yes", "true", "m", "mandatory", "required", "1", "x")
        nodes.append(FieldNode(name=name, path=name, type=typ, mandatory=mand, start=r["start"], length=r["length"]))
    nodes.sort(key=lambda f: f.start or 0)
    for a, b in zip(nodes, nodes[1:]):
        if (a.start or 0) + (a.length or 0) > (b.start or 0):
            notes.append(f"{a.name} ({a.start}–{(a.start or 0) + (a.length or 0) - 1}) overlaps {b.name} (starts at {b.start}).")
    end = max((f.start or 0) + (f.length or 0) - 1 for f in nodes)
    notes.insert(0, f"Fixed-width record of {end} characters, {len(nodes)} fields.")
    return nodes, " ".join(notes)


def _fields(fields: list[FieldNode]) -> list[FieldNode]:
    return sorted((f for f in fields if f.start and f.length), key=lambda f: f.start or 0)


# ------------------------------------------------------------------ reading
def read_record(text: str, fields: list[FieldNode]) -> dict:
    """Values of the first data line of a fixed-width sample, by the layout in `fields`."""
    line = next((l.rstrip("\r\n") for l in text.lstrip("﻿").splitlines() if l.strip()), "")
    out: dict = {}
    for f in _fields(fields):
        v = line[f.start - 1: f.start - 1 + f.length].strip()
        if f.type in ("number", "integer") and v:
            v = re.sub(r"^([+-]?)0+(?=\d)", r"\1", v)
        out[f.name] = v
    return out


# ------------------------------------------------------------------ writing (Python)
def _pad(v: str, f: FieldNode) -> str:
    n = f.length or 0
    if not v.strip():
        return " " * n
    if f.type in ("number", "integer"):
        if v.startswith("-"):
            w = v[1:]
            return "-" + ("0" * (n - 1) + w)[len(w): len(w) + n - 1]
        return ("0" * n + v)[len(v): len(v) + n]
    return (v + " " * n)[:n]


def write_record(xml_text: str, fields: list[FieldNode]) -> str:
    from lxml import etree

    root = etree.fromstring(xml_text.encode("utf-8"))
    if root.tag != WRAPPER:
        return xml_text
    out, pos = "", 0
    for f in _fields(fields):
        el = root.find(f.name)
        v = (el.text or "") if el is not None else ""
        out += " " * max(0, f.start - 1 - pos) + _pad(v, f)
        pos = len(out)
    return out


# ------------------------------------------------------------------ writing (XSLT)
def xslt_templates(fields: list[FieldNode]) -> list[str]:
    lines = ["  <!-- Fixed-width output: the record built above is written as one positional line -->",
             f'  <xsl:template match="{WRAPPER}" mode="fixed">']
    pos = 0
    for f in _fields(fields):
        n = f.length or 0
        gap = f.start - 1 - pos
        if gap > 0:
            lines.append(f"    <xsl:text>{' ' * gap}</xsl:text>")
        v = f"string({f.name}[1])"
        sp = " " * n
        if f.type in ("number", "integer"):
            z1, z = "0" * (n - 1), "0" * n
            pad = (f"<xsl:when test=\"starts-with({v}, '-')\"><xsl:text>-</xsl:text><xsl:value-of select=\"substring("
                   f"concat('{z1}', substring({v}, 2)), string-length({v}), {n - 1})\"/></xsl:when>"
                   f"<xsl:otherwise><xsl:value-of select=\"substring(concat('{z}', {v}), string-length({v}) + 1, {n})\"/>"
                   "</xsl:otherwise>")
        else:
            pad = f"<xsl:otherwise><xsl:value-of select=\"substring(concat({v}, '{sp}'), 1, {n})\"/></xsl:otherwise>"
        lines.append(f"    <!-- {f.name}: {f.start}–{f.start + n - 1} ({f.type}) -->")
        lines.append(f"    <xsl:choose><xsl:when test=\"not(normalize-space({v}))\"><xsl:text>{sp}</xsl:text></xsl:when>"
                     f"{pad}</xsl:choose>")
        pos = f.start - 1 + n if gap >= 0 else pos + n
    lines.append("  </xsl:template>")
    return lines

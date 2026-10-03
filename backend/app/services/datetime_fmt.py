"""
Date/time patterns for format-dateTime / parse-dateTime.

A pattern may be Java style ('dd/MM/yyyy HH:mm:ss', like Java users
expect) or an XSLT 2.0 picture ('[D01]/[M01]/[Y0001] [H01]:[m01]:[s01]').
Both are tokenised into one form, from which we produce: a Python strftime
pattern (processor engine), an XSLT picture (format-dateTime in the XSLT), a
Java pattern (MapStruct) and a fixed-width substring plan (parse-dateTime in
XSLT, which has no native parser).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

# token kinds: Y4 Y2 M2 M1 MON D2 D1 H2 H1 h2 m2 s2 f3 a Z lit
_JAVA = [("yyyy", "Y4"), ("yy", "Y2"), ("MMM", "MON"), ("MM", "M2"), ("M", "M1"), ("dd", "D2"), ("d", "D1"),
         ("HH", "H2"), ("H", "H1"), ("hh", "h2"), ("mm", "m2"), ("ss", "s2"), ("SSS", "f3"), ("a", "a"),
         ("XXX", "Z"), ("xxx", "Z"), ("Z", "Z")]
_STRF = {"Y4": "%Y", "Y2": "%y", "M2": "%m", "M1": "%-m", "MON": "%b", "D2": "%d", "D1": "%-d", "H2": "%H",
         "H1": "%-H", "h2": "%I", "m2": "%M", "s2": "%S", "f3": "%f", "a": "%p", "Z": "%z"}
_PIC = {"Y4": "[Y0001]", "Y2": "[Y01]", "M2": "[M01]", "M1": "[M]", "MON": "[MNn,*-3]", "D2": "[D01]",
        "D1": "[D]", "H2": "[H01]", "H1": "[H]", "h2": "[h01]", "m2": "[m01]", "s2": "[s01]", "f3": "[f001]",
        "a": "[PN]", "Z": "[Z]"}
_JAVA_OUT = {"Y4": "yyyy", "Y2": "yy", "M2": "MM", "M1": "M", "MON": "MMM", "D2": "dd", "D1": "d", "H2": "HH",
             "H1": "H", "h2": "hh", "m2": "mm", "s2": "ss", "f3": "SSS", "a": "a", "Z": "XXX"}
_WIDTH = {"Y4": 4, "Y2": 2, "M2": 2, "D2": 2, "H2": 2, "m2": 2, "s2": 2, "f3": 3}
_PIC_RE = re.compile(r"\[([A-Za-z])([^\]]*)\]")

Token = tuple[str, str]  # (kind, literal text for 'lit')


def tokenize(pattern: str) -> list[Token]:
    if "[" in pattern and _PIC_RE.search(pattern):
        return _tokenize_picture(pattern)
    out: list[Token] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "'":
            j = pattern.find("'", i + 1)
            j = len(pattern) if j < 0 else j
            out.append(("lit", pattern[i + 1:j] or "'"))
            i = j + 1
            continue
        for jt, kind in _JAVA:
            if pattern.startswith(jt, i):
                out.append((kind, ""))
                i += len(jt)
                break
        else:
            out.append(("lit", pattern[i]))
            i += 1
    return out


def _tokenize_picture(pic: str) -> list[Token]:
    out: list[Token] = []
    pos = 0
    for m in _PIC_RE.finditer(pic):
        if m.start() > pos:
            out.append(("lit", pic[pos:m.start()]))
        comp, mod = m.group(1), m.group(2)
        two = "01" in mod and "0001" not in mod
        kind = {"Y": "Y2" if mod.startswith("01") else "Y4", "M": "MON" if mod.startswith("N") else ("M2" if two else "M1"),
                "D": "D2" if two else "D1", "H": "H2" if two else "H1", "h": "h2", "m": "m2", "s": "s2",
                "f": "f3", "P": "a", "Z": "Z"}.get(comp)
        out.append((kind, "") if kind else ("lit", m.group(0)))
        pos = m.end()
    if pos < len(pic):
        out.append(("lit", pic[pos:]))
    return out


def has_time(tokens: list[Token]) -> bool:
    return any(k in ("H2", "H1", "h2", "m2", "s2", "f3") for k, _ in tokens)


def to_strftime(tokens: list[Token]) -> str:
    return "".join(t.replace("%", "%%") if k == "lit" else _STRF[k] for k, t in tokens)


def to_picture(tokens: list[Token]) -> str:
    return "".join(t.replace("[", "[[").replace("]", "]]") if k == "lit" else _PIC[k] for k, t in tokens)


def to_java(tokens: list[Token]) -> str:
    return "".join(f"'{t}'" if k == "lit" and re.search(r"[A-Za-z]", t) else (t if k == "lit" else _JAVA_OUT[k])
                   for k, t in tokens)


# ---------------------------------------------------------------- python
def _iso_in(value: str):
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    if "T" in v or " " in v[10:11]:
        return datetime.fromisoformat(v)
    return date.fromisoformat(v[:10])


def py_format(value: str, pattern: str) -> str:
    """format-dateTime: ISO date/dateTime in, any pattern out."""
    if not value:
        return ""
    d = _iso_in(str(value))
    fmt = to_strftime(tokenize(pattern))
    out = d.strftime(fmt.replace("%f", "%%f"))
    if "%f" in fmt and isinstance(d, datetime):
        out = out.replace("%f", f"{d.microsecond // 1000:03d}")
    if isinstance(d, datetime) and "%z" in fmt:
        z = d.strftime("%z")
        out = out.replace(z, (z[:3] + ":" + z[3:]) if z else "")
    return out


def py_parse(value: str, pattern: str) -> str:
    """parse-dateTime: text in the given pattern -> ISO date (or dateTime)."""
    if not value:
        return ""
    tokens = tokenize(pattern)
    fmt = to_strftime(tokens).replace("%-m", "%m").replace("%-d", "%d").replace("%-H", "%H")
    d = datetime.strptime(str(value).strip(), fmt)
    return d.isoformat(timespec="seconds") if has_time(tokens) else d.date().isoformat()


# ------------------------------------------------------------------ xpath
def xpath_parse(arg: str, pattern: str) -> Optional[str]:
    """parse-dateTime for fixed-width patterns, as substring() extraction
    (XSLT has no date parser). None when the pattern isn't fixed-width."""
    tokens = tokenize(pattern)
    pos = 1
    where: dict[str, tuple[int, int]] = {}
    for k, t in tokens:
        if k == "lit":
            pos += len(t)
            continue
        w = _WIDTH.get(k)
        if w is None:
            return None
        where[k] = (pos, w)
        pos += w

    def part(k: str, default: str) -> str:
        if k not in where:
            return f"'{default}'"
        p, w = where[k]
        return f"substring({arg}, {p}, {w})"

    if "Y4" in where:
        year = part("Y4", "1970")
    elif "Y2" in where:
        year = f"concat('20', {part('Y2', '70')})"
    else:
        year = "'1970'"
    pieces = [year, "'-'", part("M2", "01"), "'-'", part("D2", "01")]
    if has_time(tokens):
        pieces += ["'T'", part("H2", "00"), "':'", part("m2", "00"), "':'", part("s2", "00")]
    return f"concat({', '.join(pieces)})"


def zone_offset(tz: Optional[str]) -> Optional[str]:
    """'Asia/Singapore' -> 'PT8H' (current offset; fixed at generation time)."""
    if not tz:
        return None
    from zoneinfo import ZoneInfo
    off = datetime.now(ZoneInfo(tz)).utcoffset()
    if off is None:
        return None
    secs = int(off.total_seconds())
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    h, m = divmod(secs // 60, 60)
    return f"{sign}PT{h}H{f'{m}M' if m else ''}"

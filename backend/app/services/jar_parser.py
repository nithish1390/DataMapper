"""
Minimal JVM .class file parser: reads just enough of the class file format
(constant pool + method table) to list public static methods, without any
external bytecode library. Given a .jar (a zip of .class files), every class
is parsed this way and its public static methods are offered in the mapping
UI's function menu.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass


@dataclass
class JavaMethod:
    class_name: str
    method_name: str
    params: list[str]
    ret: str


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def u1(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u2(self) -> int:
        v = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u4(self) -> int:
        v = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def skip(self, n: int) -> None:
        self.pos += n


CONSTANT_UTF8 = 1
CONSTANT_INTEGER = 3
CONSTANT_FLOAT = 4
CONSTANT_LONG = 5
CONSTANT_DOUBLE = 6
CONSTANT_CLASS = 7
CONSTANT_STRING = 8
CONSTANT_FIELDREF = 9
CONSTANT_METHODREF = 10
CONSTANT_INTERFACE_METHODREF = 11
CONSTANT_NAME_AND_TYPE = 12
CONSTANT_METHOD_HANDLE = 15
CONSTANT_METHOD_TYPE = 16
CONSTANT_INVOKE_DYNAMIC = 18
CONSTANT_MODULE = 19
CONSTANT_PACKAGE = 20


def _read_class_file(data: bytes) -> tuple[str, list[tuple[str, str]]]:
    r = _Reader(data)
    magic = r.u4()
    if magic != 0xCAFEBABE:
        raise ValueError("not a .class file")
    r.u2()  # minor
    r.u2()  # major
    cp_count = r.u2()
    cp: dict[int, dict] = {}
    i = 1
    while i < cp_count:
        tag = r.u1()
        if tag == CONSTANT_CLASS:
            cp[i] = {"tag": tag, "name_index": r.u2()}
        elif tag in (CONSTANT_FIELDREF, CONSTANT_METHODREF, CONSTANT_INTERFACE_METHODREF):
            cp[i] = {"tag": tag}; r.u2(); r.u2()
        elif tag == CONSTANT_STRING:
            cp[i] = {"tag": tag}; r.u2()
        elif tag == CONSTANT_INTEGER or tag == CONSTANT_FLOAT:
            cp[i] = {"tag": tag}; r.u4()
        elif tag in (CONSTANT_LONG, CONSTANT_DOUBLE):
            cp[i] = {"tag": tag}; r.u4(); r.u4()
            i += 1  # 8-byte constants occupy two constant-pool slots
        elif tag == CONSTANT_NAME_AND_TYPE:
            cp[i] = {"tag": tag, "name_index": r.u2(), "descriptor_index": r.u2()}
        elif tag == CONSTANT_UTF8:
            length = r.u2()
            raw = data[r.pos:r.pos + length]
            r.skip(length)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            cp[i] = {"tag": tag, "value": text}
        elif tag == CONSTANT_METHOD_HANDLE:
            cp[i] = {"tag": tag}; r.u1(); r.u2()
        elif tag == CONSTANT_METHOD_TYPE:
            cp[i] = {"tag": tag}; r.u2()
        elif tag == CONSTANT_INVOKE_DYNAMIC:
            cp[i] = {"tag": tag}; r.u2(); r.u2()
        elif tag in (CONSTANT_MODULE, CONSTANT_PACKAGE):
            cp[i] = {"tag": tag}; r.u2()
        else:
            raise ValueError(f"unsupported constant pool tag {tag}")
        i += 1

    r.u2()  # access_flags
    this_class = r.u2()
    r.u2()  # super_class
    interfaces_count = r.u2()
    r.skip(interfaces_count * 2)

    fields_count = r.u2()
    for _ in range(fields_count):
        r.u2(); r.u2(); r.u2()
        attr_count = r.u2()
        for _ in range(attr_count):
            r.u2()
            length = r.u4()
            r.skip(length)

    methods_count = r.u2()
    methods: list[tuple[str, str]] = []
    for _ in range(methods_count):
        access = r.u2()
        name_index = r.u2()
        descriptor_index = r.u2()
        attr_count = r.u2()
        for _ in range(attr_count):
            r.u2()
            length = r.u4()
            r.skip(length)
        is_public = bool(access & 0x0001)
        is_static = bool(access & 0x0008)
        name = cp.get(name_index, {}).get("value")
        descriptor = cp.get(descriptor_index, {}).get("value")
        if name and name not in ("<init>", "<clinit>") and is_public and is_static:
            methods.append((name, descriptor or ""))

    class_entry = cp.get(this_class, {})
    class_name_utf8 = cp.get(class_entry.get("name_index", -1), {})
    class_name = class_name_utf8.get("value", "?")
    return class_name, methods


def _decode_descriptor(descriptor: str) -> tuple[list[str], str]:
    m = descriptor
    if not m.startswith("("):
        return [], "?"
    close = m.index(")")
    params_str, ret_str = m[1:close], m[close + 1:]

    def decode_types(s: str) -> list[str]:
        types: list[str] = []
        i = 0
        primitive = {"I": "int", "J": "long", "D": "double", "F": "float",
                     "Z": "boolean", "B": "byte", "S": "short", "C": "char", "V": "void"}
        while i < len(s):
            arr = ""
            while i < len(s) and s[i] == "[":
                arr += "[]"
                i += 1
            if i >= len(s):
                break
            c = s[i]
            if c == "L":
                end = s.index(";", i)
                full = s[i + 1:end]
                types.append(full.split("/")[-1] + arr)
                i = end + 1
            else:
                types.append(primitive.get(c, c) + arr)
                i += 1
        return types

    params = decode_types(params_str)
    ret_types = decode_types(ret_str)
    return params, (ret_types[0] if ret_types else "void")


SKIP_PREFIXES = ("META-INF/", "org/springframework/boot/loader/", "BOOT-INF/lib/", "WEB-INF/lib/")


def parse_jar(data: bytes, max_classes: int = 400) -> list[JavaMethod]:
    """Parses the jar's own classes (for a Spring Boot fat jar: only
    BOOT-INF/classes, never the bundled libraries or the launcher) and
    returns each public static method, minus main()."""
    found: list[JavaMethod] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".class") and "$" not in n
                 and not n.endswith(("module-info.class", "package-info.class"))]
        boot = [n for n in names if n.startswith(("BOOT-INF/classes/", "WEB-INF/classes/"))]
        class_names = boot or [n for n in names if not n.startswith(SKIP_PREFIXES)]
        for name in class_names[:max_classes]:
            try:
                class_name, methods = _read_class_file(zf.read(name))
            except Exception:
                continue
            for method_name, descriptor in methods:
                params, ret = _decode_descriptor(descriptor)
                if method_name == "main" and params == ["String[]"]:
                    continue
                found.append(JavaMethod(class_name=class_name.replace("/", "."),
                                        method_name=method_name, params=params, ret=ret))
    return found


_PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_CLASS_RE = re.compile(r"\b(?:public\s+)?(?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+(\w+)")
_METHOD_RE = re.compile(
    r"public\s+(?:final\s+|synchronized\s+)*static\s+(?:final\s+|synchronized\s+)*"
    r"(?:<[^>]+>\s+)?([\w.$<>\[\],?\s]+?)\s+(\w+)\s*\(([^)]*)\)")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _param_types(params: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in params:
        depth += ch == "<"
        depth -= ch == ">"
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    types = []
    for p in out:
        p = re.sub(r"@\w+(\([^)]*\))?", "", p).replace("final ", "").strip()
        types.append(p.rsplit(None, 1)[0].replace("...", "[]") if " " in p else p)
    return types


def parse_java_source(text: str) -> tuple[list[JavaMethod], str, str]:
    """Public static methods of a .java source file -> (methods, package, class)."""
    src = _strip_comments(text)
    pkg = (_PKG_RE.search(src) or [None, ""])[1]
    cls_m = _CLASS_RE.search(src)
    if not cls_m:
        raise ValueError("No class declaration found in the .java file.")
    cls = cls_m.group(1)
    fqcn = f"{pkg}.{cls}" if pkg else cls
    methods = []
    for m in _METHOD_RE.finditer(src):
        ret, name, params = " ".join(m.group(1).split()), m.group(2), m.group(3)
        types = _param_types(params)
        if name == "main" and types in (["String[]"], ["String..."]):
            continue
        methods.append(JavaMethod(class_name=fqcn, method_name=name, params=types, ret=ret))
    return methods, pkg, cls

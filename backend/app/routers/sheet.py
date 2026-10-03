import json
import re

from fastapi import APIRouter, HTTPException, UploadFile

from app.models.schemas import (
    FieldNode, MappingRule, SheetImportRequest, SheetImportResult, SheetPreview, SourceRef,
)
from app.services.llm_client import LlmError, call_llm, extract_json
from app.services.mapping_logic import build_candidate_nodes, compile_sheet_row, ensure_target_path
from app.services.parsers import flatten
from app.services.sheet_parser import (
    SheetFormatError, list_xls_sheets, list_xlsx_sheets, parse_csv_bytes,
    parse_xls_sheet, parse_xlsx_sheet, sniff_kind,
)

router = APIRouter(prefix="/api/sheet", tags=["sheet"])


@router.post("/preview", response_model=SheetPreview)
async def preview_sheet(file: UploadFile, sheet_name: str | None = None) -> SheetPreview:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        kind = sniff_kind(data, file.filename or "")
        if kind == "xlsx":
            sheet_names = list_xlsx_sheets(data)
            chosen = sheet_name if sheet_name in sheet_names else (sheet_names[0] if sheet_names else None)
            rows = parse_xlsx_sheet(data, chosen) if chosen else []
            return SheetPreview(sheet_names=sheet_names, rows=rows)
        if kind == "xls":
            sheet_names = list_xls_sheets(data)
            chosen = sheet_name if sheet_name in sheet_names else (sheet_names[0] if sheet_names else None)
            rows = parse_xls_sheet(data, chosen) if chosen else []
            return SheetPreview(sheet_names=sheet_names, rows=rows)
        return SheetPreview(sheet_names=[], rows=parse_csv_bytes(data))
    except SheetFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _resolve_with_ai(items: list[dict], ws, llm_config) -> list[dict]:
    fields_desc = "\n".join(
        f"{s.id}.{n.path}: {n.type}" for s in ws.sources for n in flatten(s.fields)
    )
    items_desc = "\n".join(f'{i + 1}. target="{it["target"]}" instruction="{it["instruction"]}"'
                            for i, it in enumerate(items))
    prompt = f"""You are converting mapping-sheet instructions into structured field mappings.
Available source fields (source_id.path : type):
{fields_desc or '(no sources parsed)'}

Items to convert (each is a target field and a free-form instruction a rule-based parser could not resolve):
{items_desc}

Reply with ONLY a JSON array (no prose, no code fences), one object per item in the same order:
[{{"target":"<target path exactly as given>","inputs":[{{"source_id":"<id>","path":"<path>"}}],"transform":"<DSL expression, or empty string for direct copy>"}}]
Available functions: COPY, CONCAT, UPPERCASE, LOWERCASE, TRIM, SUBSTRING, REPLACE, CONTAINS, STARTSWITH, ENDSWITH, STRINGLENGTH, EQUALS, NOTEQUALS, GT, LT, GTE, LTE, IF(cond,then,else), WHEN(cond1,val1,...,otherwise)."""
    return extract_json(await call_llm(prompt, llm_config))


@router.post("/apply", response_model=SheetImportResult)
async def apply_sheet(req: SheetImportRequest) -> SheetImportResult:
    ws = req.workspace
    mappings: dict[str, MappingRule] = {m.target: m for m in ws.mappings}
    added_fields: list[FieldNode] = []
    notes: list[str] = []
    needs_ai: list[dict] = []
    seq = len(ws.mappings)

    for row in req.rows:
        if not row.target_path:
            continue
        candidates = build_candidate_nodes(ws.sources, row.source_hint)
        inputs, transform, note = compile_sheet_row(row.source_path or "", row.transform or "", candidates)
        target_path = ensure_target_path(ws.target.fields, row.target_path)

        existing = mappings.get(target_path)
        if not existing:
            seq += 1
            existing = MappingRule(id=f"sheet{seq}", target=target_path, inputs=[], transform="", origin="sheet")
            mappings[target_path] = existing
        for inp in inputs:
            if not any(x.source_id == inp.source_id and x.path == inp.path for x in existing.inputs):
                existing.inputs.append(inp)
        if transform:
            existing.transform = transform
        existing.origin = "sheet"
        if note:
            existing.note = (existing.note + " | " if existing.note else "") + note
            if "Could not parse instruction" in note:
                needs_ai.append({"target": target_path, "instruction": row.transform or ""})
            notes.append(f"{target_path}: {note}")

    if needs_ai:
        try:
            resolved = await _resolve_with_ai(needs_ai, ws, req.llm)
            for item in resolved:
                target = str(item.get("target", "")).strip()
                m = mappings.get(target)
                if not m:
                    continue
                for inp in item.get("inputs", []):
                    ref = SourceRef(source_id=inp["source_id"], path=inp["path"])
                    if not any(x.source_id == ref.source_id and x.path == ref.path for x in m.inputs):
                        m.inputs.append(ref)
                if item.get("transform"):
                    m.transform = item["transform"]
                m.origin = "ai"
                m.note = None
        except LlmError as exc:
            notes.append(f"AI fallback failed for {len(needs_ai)} row(s): {exc}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"AI fallback failed for {len(needs_ai)} row(s): {exc}")

    return SheetImportResult(mappings=list(mappings.values()), target_fields_added=added_fields, notes=notes)

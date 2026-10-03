import json
import re

from fastapi import APIRouter, HTTPException, UploadFile

from app.models.schemas import (
    FieldNode, MappingRule, SheetImportRequest, SheetImportResult, SheetPreview, SourceRef,
)
from app.services.sheet_rules import import_rows
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


@router.post("/apply", response_model=SheetImportResult)
async def apply_sheet(req: SheetImportRequest) -> SheetImportResult:
    """Sheet rows -> formulas: understood locally where possible, the rest (and anything that fails the
    check) mapped by the LLM; every row reported. See services/sheet_rules.py."""
    mappings, structures, report, notes = await import_rows(req.workspace, req.rows, req.llm, req.functions)
    return SheetImportResult(mappings=mappings, target_fields_added=[], notes=notes, structures=structures,
                             report=report)

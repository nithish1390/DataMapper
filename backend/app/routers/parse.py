from fastapi import APIRouter, HTTPException

from app.models.schemas import ParseRequest, ParseResponse
from app.services.parsers import flatten, parse_auto, xsd_target_namespace

router = APIRouter(prefix="/api/parse", tags=["parse"])


@router.post("", response_model=ParseResponse)
def parse_schema(req: ParseRequest) -> ParseResponse:
    """Parses with the chosen format; if the content is clearly another format (a JSON sample under
    JSON Schema, an XML instance under XSD, …) it is parsed as that and `format` / `note` say so."""
    try:
        tree, extra, used, note = parse_auto(req.format, req.text, req.csv_header_row)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    field_count = sum(1 for n in flatten(tree) if not n.children)
    if used == "xsd":
        namespace, schema_name = xsd_target_namespace(req.text), extra
    elif used == "xml":
        namespace, schema_name = extra, None
    else:
        namespace, schema_name = None, extra
    defaults: dict[str, str] = {}
    if used == "swift":
        from app.services.swift_mt import choice_defaults
        defaults = choice_defaults(req.text, tree)
    header_row = None
    if used == "csv":
        from app.services.parsers import csv_table
        header_row = csv_table(req.text, req.csv_header_row)[2]
    return ParseResponse(tree=tree, schema_name=schema_name, field_count=field_count, namespace=namespace,
                         format=used, note=note, choice_defaults=defaults, csv_header_row=header_row)

from fastapi import APIRouter, HTTPException

from app.models.schemas import ParseRequest, ParseResponse
from app.services.parsers import flatten, parse_by_format, xsd_target_namespace

router = APIRouter(prefix="/api/parse", tags=["parse"])


@router.post("", response_model=ParseResponse)
def parse_schema(req: ParseRequest) -> ParseResponse:
    try:
        tree, schema_name = parse_by_format(req.format, req.text)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    field_count = sum(1 for n in flatten(tree) if not n.children)
    namespace = xsd_target_namespace(req.text) if req.format == "xsd" else None
    return ParseResponse(tree=tree, schema_name=schema_name, field_count=field_count, namespace=namespace)

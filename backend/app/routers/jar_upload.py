from fastapi import APIRouter, HTTPException, UploadFile

from app.models.schemas import JarFunction
from app.services.jar_parser import parse_jar

router = APIRouter(prefix="/api/jar", tags=["jar"])


@router.post("/upload", response_model=list[JarFunction])
async def upload_jar(file: UploadFile) -> list[JarFunction]:
    if not file.filename or not file.filename.lower().endswith(".jar"):
        raise HTTPException(status_code=400, detail="Please upload a .jar file.")
    data = await file.read()
    try:
        methods = parse_jar(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read jar: {exc}") from exc
    return [
        JarFunction(class_name=m.class_name, method_name=m.method_name, params=m.params, ret=m.ret)
        for m in methods
    ]

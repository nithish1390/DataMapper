from fastapi import APIRouter, HTTPException, UploadFile

from app.models.schemas import FunctionLibraryUpload, JarFunction
from app.services.jar_parser import parse_jar, parse_java_source

router = APIRouter(prefix="/api/functions", tags=["functions"])


@router.post("/upload", response_model=FunctionLibraryUpload)
async def upload_library(file: UploadFile) -> FunctionLibraryUpload:
    """Custom functions: a .jar (compiled) or a .java source file. Public
    static methods become functions in the Mapping Builder."""
    name = file.filename or ""
    data = await file.read()
    lower = name.lower()
    try:
        if lower.endswith(".jar"):
            methods = parse_jar(data)
            source = None
            kind = "jar"
        elif lower.endswith(".java"):
            text = data.decode("utf-8", errors="replace")
            methods, _pkg, _cls = parse_java_source(text)
            source = text
            kind = "java"
        else:
            raise HTTPException(status_code=400, detail="Upload a .jar or a .java file.")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read {name}: {exc}") from exc
    if not methods:
        raise HTTPException(status_code=400, detail=f"No public static methods found in {name}.")
    return FunctionLibraryUpload(
        kind=kind, file_name=name, source=source,
        classes=sorted({m.class_name for m in methods}),
        functions=[JarFunction(class_name=m.class_name, method_name=m.method_name, params=m.params, ret=m.ret)
                   for m in methods],
    )

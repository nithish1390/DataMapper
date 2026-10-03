from fastapi import APIRouter, HTTPException

from app.models.schemas import TestRunRequest, TestRunResponse
from app.services.test_run import TestRunError, run_processor, run_xslt
from app.services.xslt_gen import generate_xslt

router = APIRouter(prefix="/api/test-run", tags=["test-run"])


@router.post("", response_model=TestRunResponse)
def test_run(req: TestRunRequest) -> TestRunResponse:
    try:
        if req.engine == "xslt":
            output, warnings = run_xslt(generate_xslt(req.workspace), req.workspace, req.sample_inputs)
        else:
            output, warnings = run_processor(req.workspace, req.sample_inputs, req.output_format)
    except TestRunError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestRunResponse(output=output, engine=req.engine, warnings=warnings)

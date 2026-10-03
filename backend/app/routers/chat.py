import json
import re

from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.models.schemas import LlmProviderConfig
from app.services.llm_client import LlmError, call_llm, extract_json
from app.services.parsers import flatten

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _build_prompt(req: ChatRequest) -> str:
    ws = req.workspace
    sources_desc = "\n\n".join(
        f'{s.id} ("{s.label}", {len(s.fields)} fields):\n'
        + "\n".join(f"  {n.path}: {n.type}" for n in flatten(s.fields) if not n.children)
        for s in ws.sources
    ) or "(no sources parsed yet)"
    target_leaves = [n for n in flatten(ws.target.fields) if not n.children]
    target_desc = "\n".join(
        f"  {n.path}: {n.type}" + (" (mandatory)" if ws.target.mandatory_overrides.get(n.path, n.mandatory) else "")
        for n in target_leaves
    ) or "(not parsed yet)"
    mappings_desc = "\n".join(
        f"{m.target} <- [{', '.join(i.source_id + '.' + i.path for i in m.inputs)}] "
        f"transform={m.transform or '(direct)'}"
        for m in ws.mappings
    ) or "(none yet)"

    return f"""You are a field-mapping assistant for a data integration tool.
Sources:
{sources_desc}

Target fields:
{target_desc}

Current mappings:
{mappings_desc}

User instruction: "{req.instruction}"

Reply with ONLY JSON (no prose, no code fences), shaped exactly like:
{{"message":"one short sentence explaining the proposal","actions":[{{"op":"add","target":"<target path>","inputs":[{{"source_id":"<source id from above>","path":"<source path>"}}],"transform":"<optional DSL expression, or empty string for direct mapping>"}}]}}
Use "op":"remove" with only "target" to remove a mapping. Only reference source_id values and paths that exist above.
Available transform functions: COPY, CONCAT, UPPERCASE, LOWERCASE, TRIM, SUBSTRING, REPLACE, CONTAINS, STARTSWITH, ENDSWITH, STRINGLENGTH, EQUALS, NOTEQUALS, GT, LT, GTE, LTE, IF(cond,then,else), WHEN(cond1,val1,...,otherwise)."""


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    prompt = _build_prompt(req)
    try:
        parsed = extract_json(await call_llm(prompt, req.llm))
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="LLM reply was not a JSON object.")
    return ChatResponse(message=parsed.get("message", ""), actions=parsed.get("actions", []))


@router.post("/test")
async def test_connection(llm: LlmProviderConfig) -> dict:
    """Plain round-trip check — no JSON parsing, so any reply means 'reachable'."""
    try:
        reply = await call_llm("Reply with the single word: ok", llm)
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "reply": reply.strip()[:100]}

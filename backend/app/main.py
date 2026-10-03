import os
from pathlib import Path

from dotenv import load_dotenv

# backend/.env (if present) — e.g. LLM_BASE_URL / LLM_API_KEY / LLM_MODEL — before anything reads os.environ.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import chat, codegen, functions, jar_upload, parse, sheet, testrun

app = FastAPI(
    title="MapSheet AI API",
    description="Schema parsing, field mapping, MapStruct/XSLT codegen, and the LLM proxy "
                "for the MapSheet AI Angular frontend.",
    version="1.0.0",
)

allowed_origins = os.environ.get("CORS_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parse.router)
app.include_router(codegen.router)
app.include_router(testrun.router)
app.include_router(chat.router)
app.include_router(jar_upload.router)
app.include_router(sheet.router)
app.include_router(functions.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

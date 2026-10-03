# MapSheet AI

> **Start here: [PROJECT_GUIDE.md](PROJECT_GUIDE.md)** — how to run it, what it does, and how it is built.
> The notes below describe the original rebuild.

A visual schema/field mapper — drag-and-drop source → target mapping, a small
transform DSL (CONCAT/IF/WHEN/EQUALS/GT/…), mapping-sheet import, an AI assistant, and a
"Download project" button that generates a real **MapStruct**-based Spring Boot project
(plus matching XSLT).

This is the **Angular + Python** rebuild of an earlier single-file HTML prototype. Splitting
it into a real frontend/backend does two things beyond "cleaner code":

1. **The LLM calls now actually work everywhere.** The prototype called an LLM API directly
   from the browser, which is blocked by CORS outside of a narrow embedded-preview context.
   Here, the **backend** calls the LLM server-side — no browser restriction, and your API key
   never has to sit in client-side JavaScript.
2. **Conversion logic lives on the backend.** Schema parsing, the transform DSL, MapStruct/XSLT
   code generation, jar bytecode parsing, and mapping-sheet compilation are all pure Python
   services with no UI concerns — the Angular app is purely presentation + orchestration.

## Architecture

```
datamapper/
├── backend/                    FastAPI (Python) — all "brains"
│   └── app/
│       ├── models/schemas.py       Pydantic models (source of truth for the API shape)
│       ├── services/
│       │   ├── parsers.py          JSON Schema / sample / XSD / CSV / fixed width / SWIFT / POJO → tree
│       │   ├── transform_dsl.py    {0}/{1}/$var DSL: parse, evaluate, → Java, → XPath
│       │   ├── codegen.py          MapStruct mapper, XSLT, JAXB classes, pom.xml, Spring Boot files
│       │   ├── mapping_logic.py    fuzzy path resolution + mapping-sheet instruction compiler
│       │   ├── jar_parser.py       pure-Python JVM .class bytecode parser
│       │   ├── llm_client.py       server-side LLM proxy (OpenAI SDK, any OpenAI-compatible endpoint)
│       │   ├── sheet_parser.py     CSV/XLSX reading (openpyxl)
│       │   └── test_run.py         Test/Run tab: sample input → mapped JSON/XML preview
│       └── routers/                one FastAPI router per concern, thin — just calls services
│
└── frontend/                   Angular (standalone components + signals)
    └── src/app/
        ├── core/
        │   ├── models/api.models.ts        TypeScript mirror of the backend's Pydantic models
        │   └── services/
        │       ├── api.service.ts          typed HttpClient wrapper — the only thing that calls the API
        │       ├── workspace.service.ts    all app state, as signals (sources, target, mappings, …)
        │       └── toast.service.ts
        └── features/mapper/components/
            ├── field-tree/          recursive drag/drop schema tree (shared by source + target)
            ├── source-panel/        multi-source accordion
            ├── target-panel/        editable target tree + embeds variables-panel
            ├── variables-panel/     temp placeholders ($name)
            ├── mapping-canvas/      center detail editor + all-mappings list + function-menu
            ├── bottom-panel/        Processor / XSLT / Test-Run tabs
            ├── chat-drawer/         AI assistant (propose → explicit apply)
            ├── settings-modal/      project + LLM provider config, jar upload, connection test
            ├── sheet-import-modal/  CSV/Excel mapping-sheet import
            └── mapper-page/         composes everything + the resizable 3-column layout
```

The frontend never talks to the LLM, generates code, or parses schemas itself — every one of
those is a backend endpoint. `workspace.service.ts` holds UI state (which panel is open, drag
selection, etc.) and the mapping data; `toWorkspace()` on it produces the exact JSON payload
every backend endpoint expects.

## Running it

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

All LLM calls use the OpenAI SDK against an OpenAI-compatible endpoint
(`OpenAI(base_url=..., api_key=...).chat.completions.create(...)`) — Ollama, vLLM, LiteLLM,
OpenAI/Azure OpenAI or a gateway. Configure it in **Settings → LLM API** (base URL, API key, model,
extra headers), or set defaults in `backend/.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).

API docs are auto-generated at `http://localhost:8000/docs` once it's running.

### Frontend

```bash
cd frontend
npm install
npm start
```

Opens on `http://localhost:4200`. The dev server proxies `/api/*` to `http://localhost:8000`
(see `proxy.conf.json`), so no CORS configuration is needed for local development.

For a production deployment, build with `npm run build`, serve `dist/mapsheet-ai-frontend`
from any static host, and set `CORS_ORIGINS` on the backend to that host's origin.

## What's real vs. a documented simplification

Everything listed under `services/` above is fully implemented and was tested end-to-end
against a realistic ISO 20022 (pain.001) scenario during development — parsing a multi-level
XSD, building conditional mappings (`IF(GT({0}, 0), {0}, '1')`), and generating a correct,
compiling-shaped MapStruct interface with real nested `@Mapping` paths, plus the matching XSLT.

A few things are intentionally simplified, matching the same limitations the prototype had:

- Non-XSD target/source formats (JSON Schema, CSV, fixed width, SWIFT MT, POJO) still generate a
  single **flattened** POJO — only XSD gets real nested JAXB classes.
- `for-each` mappings generate a loop/`@Mapping(ignore=true)` scaffold; per-item field mapping
  for a repeating element still needs to be filled in by hand.
- The mapping-sheet CSV path does a simple comma-split; Excel via `openpyxl` handles quoting
  correctly.
- The Test/Run tab is a lightweight Python reimplementation of "what would this mapping
  produce", not the actual compiled Java — treat it as a fast preview.

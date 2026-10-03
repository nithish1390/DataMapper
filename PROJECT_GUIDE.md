# MapSheet AI — Project Guide

**MapSheet AI** is a browser-based, visual **data-mapping workbench**. You load a source schema and a target schema
(XSD, XML sample, JSON Schema, JSON sample, CSV / Excel, fixed width, SWIFT MT, Java class / record), map fields by drag and drop or with XPath-style
formulas, add logic (loops, grouping, conditions, copy), test the result on real sample data,
validate it against the target XSD, and download a ready-to-run Spring Boot project
(MapStruct mapper + XSLT). Mapping sheets (Excel / CSV) can be imported, and an AI assistant
(any OpenAI-compatible LLM) helps with mappings and with sheet rows it can't parse on its own.

---

## 1. Getting started

### Prerequisites
- Python 3.11+ (tested with 3.13)
- Node.js 18+ and npm (tested with Node 24)
- Optional: Java 17/21 + Maven, to build the generated Spring Boot project

### Backend (FastAPI, port 8000)
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # optional: default LLM settings
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

`backend/.env` (all optional — the same values can be entered in **Settings**):
```
LLM_BASE_URL=http://localhost:11434/v1   # any OpenAI-compatible endpoint
LLM_API_KEY=dummy
LLM_MODEL=llama3.1
```

### Frontend (Angular, port 4200)
```bash
cd frontend
npm install
npm start                     # ng serve, proxies /api to http://localhost:8000
```
Open http://localhost:4200.

> If port 8000 is taken by something else, start the backend on another port and change
> `frontend/proxy.conf.json` to match.

---

## 2. A typical session

1. **Source** (left): choose the format, upload or paste the schema or a sample, *Parse fields*.
   If the content is clearly another format (e.g. a JSON sample under JSON Schema, an XML instance
   under XSD), it is detected, parsed as that format, and the format selector switches to it.
   The source id (`$s1`) is how formulas refer to it. Add more sources with *+ Add source*.
2. **Target** (right): choose the format, upload or paste, *Parse fields*.
3. **Map**:
   - drag a source field onto a target row (or type a formula in the row's Formula cell);
   - drag a source *container* onto a target container — children are mapped by name, with a
     For-Each when both repeat, and renamed fields matched by prefix (e.g. `BIC` → `BICFI`);
   - right-click a target row for **Statement › Surround with For-Each / For-Each-Group / If /
     Choice**, Copy-Of, Copy / Paste formula, Clear mapping.
4. **Mapping Builder** (centre): select any target row to edit its formula with the Functions,
   Variables and Constants tabs. Edits are a draft until **Apply** (Ctrl/⌘+Enter); **Save**
   applies and saves the session.
5. **Test / Run** (bottom): paste a sample input and run either the generated XSLT or the
   processor rules; see the output immediately.
6. **✓ Validate**: coverage summary (mapped / not mapped / mandatory missing), mapping problems,
   and — with a sample — the generated output validated against the target XSD, each error
   explained and linked to its field. The sample itself is also checked against the source XSD.
7. **⬇ Download project**: a Spring Boot + MapStruct project with JAXB model classes, the XSLT,
   custom-function classes and a REST endpoint.
8. **🗂 Sessions**: name the work and save it as `<name>.mapsheet.json`; open it later to
   continue. The app also auto-saves a draft in the browser and offers to restore it.

---

## 3. Features

### Mapping
- **Visual tree with logic rows** — statements appear as rows of the target tree:
  `[For-Each]`, `[For-Each-Group]`, `[Choice] › [When] / [Otherwise]`, `[If]`, `[Copy-Of]`.
  Each `[When]` / `[Otherwise]` has its own copy of the element with its own mappings.
- **Mapping lines** between source and target (All / Selected / Off).
- **XPath-style formulas** — `Name/FullName`, `../PmtInfId`, `$s1/Document/...`,
  `count(Item) > 0`, `concat(a, ' ', b)`, `if(cond, a, b)`, `position()`.
- **Copy-Of follows the target schema** — same-named children copied, renamed ones matched by
  prefix, source-only elements reported, any sub-field overridable.
- **XML attributes** (`@Ccy`) and **xs:choice** (pick the alternative with ○/◉).
- **SWIFT MT**: all five blocks and every field of the message type (MT101/103/199/202/202COV/299/
  900/910/940/950 catalogued), options as choices (50A / 50F / 50K), components (32A → Date /
  Currency / Amount) — paste a message, or just `MT103` for the field list.
- **Fixed width**: upload or paste a layout definition (Field / Start / Length / Type, as text, CSV or
  Excel); fields show their positions. As a source, values are cut from the sample line. As a target,
  the result is a padded record (text left-aligned, numbers zero-padded); you can choose XML output instead.
- **Typed variables** in the target tree: global (top of the tree) or local, placed before any element
  and so also inside For-Each / When / If. Types are string, integer, decimal, boolean, date, dateTime
  and node. Use one in a formula as `$name`. A node variable can be counted, used as the base of a path
  or used as the select of a For-Each.
- A **root condition**, and **custom functions** (upload `.jar` or `.java`;
  grouped by your own names; `.java` sources ship in the downloaded project).

### XSLT 1.0 / 2.0
- One switch (Mapping Builder bar, XSLT tab, Test / Run).
- **1.0**: pure XSLT 1.0, tested with libxslt (lxml). **2.0**: `version="2.0"`, tested with
  Saxon-HE; adds regex `replace` / `matches`, `string-join`, `min` / `max` / `avg` / `abs`,
  time-zone dates, `format-dateTime`, and For-Each-Group (`current-group()`,
  `current-grouping-key()`).
- Formulas using 2.0-only features are flagged red when 1.0 is selected.
- Date helpers: `current-dateTime('Asia/Singapore')`, `current-date(zone)`,
  `format-dateTime(v, 'dd/MM/yyyy HH:mm')`, `parse-dateTime(v, 'dd/MM/yyyy')`,
  `format-number(v, '#,##0.00')`.

### Mapping sheets (Excel / CSV)
- Import `.xlsx`, legacy `.xls` or `.csv` (Apple Numbers files are detected and you are asked to
  export them). Pick the columns for source path, target path and rule.
- Paths are resolved fuzzily (XPath style or dotted, with or without the root); plain-text
  rules the parser can't understand are sent to the LLM for a structured mapping.
- Export the current mappings back to CSV.

### Checks
- Red rows: mandatory fields not mapped, formula errors, paths missing from the source,
  For-Each without select, When without test, unpicked choice alternatives with mappings.
- Validate screen with XSD validation of the generated output and of the sample input.

### AI assistant
- Chat drawer: describe a mapping in words; the assistant proposes changes you apply explicitly.
- Uses the **OpenAI SDK** against any OpenAI-compatible endpoint (base URL, API key, model and
  extra request headers in Settings, or `backend/.env`).

### Workspace
- Themes: System / Light / Dark, seven palettes plus custom colours, compact or comfortable rows.
- Confirmation before every delete; warning before closing with unsaved changes.

---

## 4. Architecture

```
datamapper/
├── backend/                      FastAPI — all parsing, generation and execution
│   ├── requirements.txt
│   └── app/
│       ├── main.py               app, CORS, routers, .env loading
│       ├── models/schemas.py     Pydantic models (the API contract)
│       ├── routers/              parse · codegen (preview, links/analysis, validate, project zip)
│       │                         · test-run · chat · sheet · functions · jar
│       └── services/
│           ├── parsers.py        XSD (attributes, choices, simple types) / JSON / CSV / fixed width / SWIFT / POJO → tree
│           ├── fixed_width.py    fixed-width layout definitions, record reader / writer (+ XSLT)
│           ├── transform_dsl.py  formula language: parser, evaluator, → XPath 1.0/2.0, → Java
│           ├── structure.py      shared model: statements, branch scopes, for-each context, copy pairing
│           ├── xslt_gen.py       XSLT 1.0 / 2.0 generation
│           ├── test_run.py       Test / Run: XSLT execution (lxml / Saxon) and the processor engine
│           ├── links.py          source→target links and per-row problems
│           ├── validation.py     coverage + XSD validation with explanations
│           ├── codegen.py        MapStruct mapper, JAXB classes, pom.xml, Spring Boot files
│           ├── mapping_logic.py  fuzzy path resolution, mapping-sheet rule compiler
│           ├── datetime_fmt.py   Java / picture date patterns
│           ├── jar_parser.py     .class / .jar and .java parsing for custom functions
│           ├── sheet_parser.py   .xlsx / .xls / .csv reading
│           └── llm_client.py     OpenAI SDK client
│
└── frontend/                     Angular 18 (standalone components + signals)
    └── src/app/
        ├── core/services/        workspace (all state + target rows), api, session, formula helpers
        ├── shared/components/    context menu, confirm dialog, theme picker, toast
        └── features/mapper/components/
            ├── source-panel, field-tree      source trees
            ├── target-panel, target-mapper   target tree with statement rows and formula column
            ├── formula-builder               Mapping Builder (centre)
            ├── mapping-lines                 source → target lines
            ├── bottom-panel                  Processor / XSLT / Test-Run tabs
            ├── validation-modal, sessions-modal, custom-functions-modal,
            ├── settings-modal, sheet-import-modal, chat-drawer, variables-panel
            └── mapper-page                   layout, top bar, shortcuts
```

The two Test / Run engines (executed XSLT and the processor rules) share one model
(`structure.py`), so they produce the same output — this is how the mapping logic is tested.

---

## 5. Useful references
- `CHANGES.md` — what changed, round by round.
- `backend/.env.example` — LLM defaults.
- `http://localhost:8000/docs` — every API endpoint, with a try-it-out form.

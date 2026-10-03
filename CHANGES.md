# Changes — round 19: mapping sheet export fixed

- **Export mapping sheet** produced only the header line. It still read the old drag-and-drop input lists,
  which formula mappings don't use. It now exports the mapping as the target tree shows it, one row per
  mapped field, statement and variable:
  `Target Path, Target Field, Kind, Mapping / Formula, Source Fields, Inside, Mandatory, Data Type`
  - Kind: Value, Copy-Of, Copy-Of (from parent), For-Each, For-Each-Group, Choice, When, Otherwise, If,
    Variable (type), Global variable (type).
  - Source Fields: the source paths the row really reads (`$s1/Document/…`), from the resolved links.
  - Inside: the statements around the row, e.g. `[For-Each $s1/…/PmtInf] › [When PmtMtd = 'TRF']`.
  - Also exported: the root condition (first row), For-Each-Group's `group by` key, fixed-width positions
    in Data Type (`string (1–10)`), and a note on mappings under a choice alternative that isn't selected.
  - Checked with every format: XSD (with attributes, Copy-Of children, nested For-Each, If, collapsed tree),
    JSON, CSV, fixed width, SWIFT MT and POJO sources and targets, and two sources.
  - Proper CSV quoting (formulas keep their commas), UTF-8 with BOM for Excel, and the file is named after
    the session (`<session>-mappings.csv`).

---

# Changes — round 18: fixed width; Swagger removed

- New format **Fixed width (layout definition)** for sources and targets. Upload or paste the definition:
  ```
  Field       Start   Length   Type
  -----------------------------------
  AccountNo   1       10       String
  Name        11      15       String
  Amount      26      11       Decimal
  Currency    37      3        String
  ```
  - Columns can be separated by spaces, tabs, `|`, `,` or `;`, so an Excel definition works too (the
    workbook is converted and stays Fixed width). The header line is optional; `End` may replace `Length`,
    and a `Mandatory` / `Required` (Y/N) column sets (M). Field names may contain spaces, and 0-based starts
    are detected.
  - Types: String / Char / X / Date → text; Decimal / Number / Amount → number; Integer / Int / N → integer;
    Boolean.
  - Clear errors for non-numeric starts or lengths. Overlapping fields are reported in the parse note,
    together with the record length.
  - Each field shows its position as `start+length` (e.g. `26+11`) in the source and target trees.
- **As a source**: Test / Run cuts each field from the first data line of the sample and trims it; numbers
  lose their leading zeros (`00000150.50` → `150.50`).
- **As a target**: the result is one positional record. Text is left-aligned and padded with spaces; numbers
  are right-aligned and padded with zeros (`-` stays in front). Empty fields are spaces, values that are
  too long are cut, and gaps are spaces. The same **Output: Fixed width | XML** switch as for SWIFT (XML is
  `<Record>…</Record>`). The generated XSLT writes the record itself (text output), identical to the processor
  in XSLT 1.0 and 2.0.
- **Swagger / OpenAPI removed** from the format lists (and from auto-detection). Sessions saved with it open
  as JSON Schema.

---

# Changes — round 17: CSV header row

- When the format is **CSV** (source or target), the loader shows a **Header row** setting:
  - **Auto-detect** (default): finds the first line with as many columns as the table, so title or
    comment lines above it are skipped; it shows "→ row n";
  - **Row number**: the line that holds the column names (1 = first line; blank lines count, as in an editor);
  - **No header row**: columns are named column1, column2 …
- Below the setting is a numbered preview of the first 12 lines. Click a line to make it the header:
  it is highlighted, lines above it are struck through, and lines below are data.
- When the fields are already loaded (✎ Edit input), changing the header row re-parses straight away.
- The delimiter (, ; tab |) is now detected by the most consistent column count, so title lines no
  longer confuse it. Duplicate column names get suffixes (`amount`, `amount_2`).
- **Excel workbooks** (`.xlsx` / `.xls`) uploaded as a source or target are converted to CSV text, and the
  format switches to CSV. A **Sheet** selector appears when the workbook has more than one sheet. Before,
  the file was read as text and showed up as binary garbage. Other binary files are rejected with a clear message.
- Test / Run reads the CSV sample with the same header row (the first data row below it). The setting
  is saved with the session.

---

# Changes — round 16: SWIFT MT output

- When the target is a SWIFT MT message, the result is written as an **MT message** by default:
  `{1:…}{2:…}{3:{121:…}}{4:` + `:tag:value` lines + `-}{5:…}`. A switch **Output: SWIFT MT | XML** under the
  Target header (and in Test / Run) changes it to XML; the choice is saved with the session.
- The generated XSLT produces the MT text itself (`xsl:output method="text"`): it builds the message, then
  writes it with templates in mode `mt` (XSLT 1.0 uses `exsl:node-set`). So the XSLT tab, Test / Run and the
  downloaded project all give the same MT message. The processor engine writes it identically.
- XML output is wrapped in `<SwiftMessage type="MT103">`, so it is well-formed (before, the five blocks were
  five separate root elements).
- Fields: a mapped `Value` is written as is; otherwise the field is built from its components using the
  field format. Examples: `/` before an account, the account and the BIC on separate lines (option A/D),
  name and address lines, a decimal comma in amounts (`150.50` → `150,50`, `250` → `250,`), and field 61's
  `//` reference with supplementary details on the next line. Empty fields are left out.
- Headers: block 1 defaults to `F01` + LT address + `0000000000`; block 2 is written in the input (`I`) or
  output (`O`) layout, with the message type from the target (MT202 COV adds `{119:COV}`). Blocks 3 and 5
  are written only when they have tags.
- Tested round trip: MT103, MT101 and MT940 copied through a SWIFT → SWIFT mapping come back
  unchanged.

---

# Changes — round 15: Clear mapping at any level

- Right-click any target row › **Clear mapping**, always after a confirmation that says how many mappings,
  statements and variables will be removed:
  - a field: its own mapping;
  - a parent (or its For-Each / If / Choice row): the parent and every child below it, including the
    statements and local variables inside it and the mappings in its [When] / [Otherwise] branches;
  - a [When] / [Otherwise] row: the mappings inside that branch (the branch is kept);
  - the root element: **Clear all mappings** (every mapping, statement and global variable);
  - the Variables header: **Clear all variables**.
- Only mappings are removed; target fields are never deleted. "Delete statement / [When] / variable"
  remains a separate menu item.

---

# Changes — round 14: typed variables in the target tree

- **Global variables** sit at the top of the target tree under *Variables (n)* (toolbar **＄ Variable**,
  header **+ add**, or right-click › *Add global variable*). In XSLT they become top-level `xsl:variable`s.
- **Local variables**: right-click any target row › *Add variable here (before this element)*. The
  `$name - [Variable]` row is placed before that element, in the same scope: inside a For-Each, a
  When / Otherwise or an If. It is evaluated once for each item or branch, e.g. `$pos := position()`.
- Types: **string, integer, decimal, boolean, date, dateTime, node** (a badge on the row). In XSLT 2.0 the
  type becomes `as="xs:…"`. The processor engine casts the value the same way.
- **node** variables hold source nodes (`$payments := $s1/Document/CstmrCdtTrfInitn/PmtInf`). You can
  use them in `count($payments)`, in paths (`$payments/PmtInfId`) and as the select of a For-Each.
- In the Mapping Builder, a variable row shows its **Name** and **Type**. Renaming a variable updates every
  `$ref` to it in all formulas.
- `if(...)` / `when` can now be used inside other functions (e.g. inside `concat`), in XSLT 1.0 and 2.0.
- Problems are flagged red: invalid or duplicate names, names that clash with a source id, and empty
  formulas.

---

# Changes — round 13: SWIFT MT

- ✎ Edit input (each source and the target): reopens the current schema / payload — pasted or uploaded —
  as editable text with ↻ Re-parse and Cancel. Mappings are kept.
- SWIFT MT parsing uses **swift-parser-py** (MIT, vendored in `backend/app/vendor/swift_parser_py`
  because its PyPI release depends on the obsolete `typing` backport, which breaks Python 3).
- The source tree shows **every field of the message type in all five blocks**: block 1 basic header,
  block 2 application header (input and output), block 3 user header tags (103, 108, 111, 113, 115,
  119, 121 UETR, 165, 423, 424, 433, 434, 106), block 4 text and block 5 trailers (CHK, TNG, PDE, PDM,
  DLM, MRF, SYS, MAC, PAC).
- Field catalogue for MT101, MT103, MT199, MT202, MT202 COV, MT299, MT900, MT910, MT940, MT950: every
  field and option, mandatory / optional, repeating, and sequences (MT101 sequence B, MT202 COV
  sequence B, MT940 statement lines). Other MTs show the fields present in the message. Pasting just
  "MT103" gives the full field list without a sample.
- Options form a choice (50A / 50F / 50K, 52A / 52D, 59 / 59A / 59F …): ○/◉ in the source tree; the
  option the message contains is pre-selected, the others are struck through and folded (still mappable).
- Composite fields are split into components (32A -> Date / Currency / Amount, 50F -> Party_Identifier +
  Name_And_Address lines …) with `Value` holding the whole raw field; amounts use a decimal point
  (`1234,56` -> `1234.56`) so they can be summed and mapped to decimal targets.

---

# Changes — round 12: input formats

- Format auto-detection: parsing a JSON sample as "JSON Schema" (or an XML instance as "XSD", or SWIFT
  pasted under the wrong format, …) no longer fails — the content is detected, parsed as the right
  format, the selector switches to it and a note says so.
- New **XML sample** format: elements, @attributes, repeated elements as arrays (structure merged over
  all occurrences), typed values, root namespace — works as source and target, XSLT 1.0 / 2.0 included.
- JSON sample: top-level arrays, keys merged across all array items, arrays of values marked repeating;
  JSON / YAML accepted for samples, JSON Schema and Swagger / OpenAPI.
- SWIFT MT: block 1/2 headers (Sender_BIC, Message_Type, Receiver_BIC), multi-line values (50K / 59
  name and address), repeated tags as repeating fields; Test / Run reads samples the same way.
- Java: fields with initialisers, annotations (@NotNull -> mandatory), nested and sibling classes as
  objects, List / Set / arrays as repeating elements with their item fields, records; statics skipped.
- CSV: delimiter detected (, ; tab |), quoted values, headers turned into usable field names.

---

# Changes — round 11: renamed to MapSheet AI

- Red markers always match Validate: the background check now re-runs on every relevant change
  (including the XSLT version, sources, variables, custom functions and session restore), ignores
  out-of-date responses, and Validate refreshes it. Choices filled through a parent's Copy-Of are no
  longer flagged red.
- The app is now **MapSheet AI** everywhere: top bar (tagline "AI data mapping · Excel mapping sheets"),
  browser tab, API title, generated-code comments, docs. Sessions save as `<name>.mapsheet.json`;
  older `.dmsession.json` files, auto-saves and theme choices are still read.
- Settings: removed the two LLM explanation notes.
- New `PROJECT_GUIDE.md`: how to start, what the app does, features and architecture.

---

# Changes — round 10

- Red now only means a problem: statement rows ([For-Each], [Choice], [If] …) use the accent colour.
- Target fields can't be deleted any more (right-click › Field has Mark mandatory / Add child / Rename);
  rows offer Clear mapping and statement actions only.
- Attributes: an element whose only children are attributes (e.g. InstdAmt + @Ccy) always shows its
  attribute rows — it is never collapsed — including under a Copy-Of.
- Opening a session or restoring the auto-save re-parses the stored schemas with the current parser, so
  sessions saved by an older version pick up newer details (attributes, choice markers, types).

---

# Changes — round 9

- Validate also checks the Test / Run sample against the source XSD ("Input sample vs source XSD"), so
  errors caused by the input are visible as such; choice errors say which option is mapped and which one
  the sample contains. Importing a mapping sheet sets XSLT 2.0.
- Source column: each opened source now fills the column and its field tree scrolls on its own with a
  visible scrollbar (like the Target tree). Floating ▲▼ scroll buttons removed from both columns;
  headers, padding and gaps tightened; schema loaders stay folded away after parsing.
- Mapping Builder: the Generated XSLT preview fills the remaining height.
- XSLT 1.0: 2.0-only functions no longer write a "needs XSLT 2.0" text into the output. They degrade to
  the nearest 1.0 value (e.g. current-dateTime(zone) -> EXSLT date:date-time() in the server zone) and stay
  flagged red. Fixes the CreDtTm "not a valid ISODateTime" error under 1.0.
- Validate: each XSD error now names the target field, shows its formula and explains the cause — e.g.
  "the Test / Run sample has no value at $s1/.../ReqdExctnDt, so the mandatory field is written empty" or
  "Map one of: IBAN | Othr (it is a choice)". Click an error to jump to the field. Failing XSD checks open
  their error list automatically.

---

# Changes — round 8

- Mapping Builder (renamed from the formula builder): edits are a draft until **✓ Apply**
  (Ctrl/⌘+Enter); **💾 Save** applies and saves the session (Ctrl/⌘+S); **↺ Revert** discards.
  Switching rows with unapplied edits asks whether to apply them; applying an empty formula asks before
  removing the mapping. Statement buttons (For-Each, For-Each-Group, If, Choice, Copy-Of) on the Functions tab.
- XSLT 1.0 / 2.0 (Mapping Builder bar, XSLT tab, Test / Run — one setting, saved with the session):
  1.0 generates a pure XSLT 1.0 stylesheet and Test / Run executes it with libxslt (lxml);
  2.0 generates `version="2.0"` (single values read as `(path)[1]`) and runs it with Saxon-HE.
  Formulas using 2.0-only features are flagged red when 1.0 is selected.
- Options follow the version: the Functions tab only lists what the selected version supports, with new
  2.0 data-manipulation functions (regex `replace`, `matches`, `string-join`, `abs`, `min`, `max`, `avg`,
  time-zone dates, `format-dateTime`) and **For-Each-Group** looping (`group by`, `current-group()`,
  `current-grouping-key()`). `format-number` added for both versions.
- Themes: palette renamed to "Classic Blue"; new **Custom…** palette with colour pickers (accent,
  mapping lines, condition lines, formula cells). Product names removed from UI, code, prompts and docs.

---

# Changes — round 7: Sessions

- 🗂 Sessions (top bar, shows the session name and ● when there are unsaved changes):
  name the session, **Save** it to `<name>.mapsheet.json` in any state (Ctrl/⌘+S works anywhere),
  **Open** a saved file to restore everything exactly (schemas, mappings, statements/branches, variables,
  custom functions, Test/Run samples, settings, expanded rows), or start a **New** session.
  The LLM API key and header values are left out of the file unless you tick the option.
- Reload / close: the session is auto-saved in this browser (IndexedDB) and the browser's "Leave site?"
  prompt appears when there are unsaved changes. Browsers don't allow a custom dialog or a file download at
  that moment, so on the next start the app offers to restore it. Drafts are also written a few seconds
  after every change; Sessions › Restore / Discard manages it.

---

# Changes — round 6

- Copy-Of now follows the **target** schema: every target sub-field is filled from the source sub-field
  with the same name, or — when the name changed between versions — a unique source field whose name is a
  prefix of it (pain.001.001.03 `BIC` -> .06 `BICFI`). Source-only elements are no longer copied into the
  output (reported instead), repeating elements loop, attributes are copied. Any sub-field under a Copy-Of
  can be overridden by typing/dropping a formula on its row. A whole pain.001.001.03 -> .06 document built
  from Copy-Ofs now validates against the .06 XSD.
- Mapping Builder: Data tab removed (Functions, Variables, Constants). Drag fields from the Source panel
  into the formula instead.
- 🎨 Theme (top bar): System / Light / Dark, 7 colour palettes (Indigo, Ocean, Forest, Sunset, Plum,
  Graphite, Classic Blue) and Compact / Comfortable density; remembered in this browser.
- Source and Target panels: always-visible scrollbars and floating ⤒ ▲ ▼ ⤓ scroll buttons.

---

# Changes — round 5

- XML attributes: XSD attributes (incl. simpleContent extensions and attributeGroups) are parsed as `@Name`
  fields in both trees (icon `@`, `(M)` when use="required"). Elements such as `InstdAmt` keep their own
  value *and* expand to their attributes. Formulas use `Amt/InstdAmt/@Ccy`. XSLT writes `xsl:attribute`,
  the processor engine and XSD validation handle them, Copy-Of copies attributes too, dropping a container
  maps attributes and values by name, and the JAXB classes get `@XmlAttribute` / `@XmlValue`
  (MapStruct maps `instdAmt.value` and `instdAmt.ccy`). Simple types now resolve through named
  restrictions, so e.g. an amount is typed as a number.
- Copy-Of on elements: a plain source path mapped onto an element that has children is now a Copy-Of
  automatically (value-of of a whole element isn't meaningful) — in the XSLT, both test engines, the
  lines and the tree. Its sub-fields show the source path they're copied from. Existing mappings saved
  in value-of mode (like PstlAdr / DbtrAgt / FinInstnId) are picked up without re-mapping.
- ✓ Validate opens a Validate screen: valid / not valid, target fields / mapped (with %) / not mapped /
  mandatory missing / optional not mapped / problems. Click a number to list those fields (filterable);
  click a field to jump to it in the Target tree. If a Test / Run sample is present, the generated XSLT
  is run and its output is validated against the target XSD (errors listed with line numbers).

---

# Changes — round 4

- LLM: every call now uses the **OpenAI SDK** (`openai` package) against an OpenAI-compatible endpoint;
  the Anthropic SDK and the built-in provider are removed. Settings → LLM API: base URL (the SDK appends
  `/chat/completions`), API key (`dummy` if empty), model, headers (`default_headers`). `.env` fallbacks:
  `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- Settings › Custom LLM API: add any number of request headers (name / value, values hidden unless
  "show values" is ticked). They're sent with every call (chat, Test connection, sheet AI fallback) and
  replace a default of the same name, e.g. a custom `Authorization` replaces the Bearer token.
- Mapping Builder shows the selected row's mapping again (an Angular signal-write in an effect was
  silently rejected, leaving the box empty). Invalid formulas / rows with problems: red border + reasons.
- Date/time: `current-dateTime('Asia/Singapore')` now really uses that zone (+08:00); also
  `current-date(zone)`, `format-dateTime(value, pattern)`, `parse-dateTime(value, pattern)`.
  Patterns: Java style (`dd/MM/yyyy HH:mm:ss`, `yyyyMMdd`, `dd-MMM-yy`) or XSLT pictures (`[D01]/[M01]/[Y0001]`).
  The XSLT uses XPath 2.0 date functions, so the XSLT engine now runs **Saxon-HE** (`pip install saxonche`);
  stylesheets keep version="1.0" and run in Saxon's backwards-compatible mode. lxml is the fallback.
- Source tree (and Data tab): the reference mapper type icons (ABC / 123 / 1.2 / T/F / ▤), `(M)` mandatory, `[*]` repeating;
  the target tree uses the same markers.
- Copy-Of: every sub-field under it shows the source path it is copied from (read-only), mapping lines
  are drawn for each, mandatory target sub-fields missing in the source are flagged red, and extra
  source children that the target doesn't define are reported.

---

# Changes — round 3

- Target tree uses the same font as the source tree; the `?` optional marker is gone
  (`*` / `+` still mark repeating elements).
- Red rows: mandatory field/element not mapped (only where its parent is actually written),
  formula errors, source paths that don't exist, For-Each without select, [When]/[If] without test,
  Copy-Of without source, mapped choice options that aren't the selected one, and choices with no
  option mapped. Parent rows get a red marker so collapsed problems stay visible; hover for the reason.
- xs:choice: alternatives show ○/◉ — click (or right-click › Use this choice option) to pick one;
  the others are struck through and not written.
- Centre panel, Choice: "Choice logic" shows every [When]/[Otherwise] as an expandable card with its
  test (editable) and the mappings inside that branch, each with delete; + When / + Otherwise / delete Choice.
- Every delete asks "Yes, delete / No" first (mappings, statements, branches, fields, sources,
  variables, custom-function libraries; also clearing a formula).
- Custom functions (top bar, next to Import mapping sheet) replace "Functions jar": upload .jar or
  .java files under a group name; each library is its own group in Functions, can be renamed or deleted.
  Spring Boot fat jars contribute only their own classes; main() and launcher classes are skipped.
  Uploaded .java classes are included in the downloaded project.
- Closing or refreshing the tab asks for confirmation when there is unsaved work.

---

# Changes — round 2: Visual mapper experience

## Target tree = the mapping 
- Statements are rows of the target tree: `Party - [For-Each]`, `Contact - [Choose]` ›
  `[When]` / `[Otherwise]`, `X - [If]`, `X - [Copy-Of]`, each with an inline XPath formula column.
- Each `[When]` / `[Otherwise]` holds its **own copy of the element with its own mappings**
  (branch-scoped), e.g. Contact under When #1 maps HomePhone, under When #2 WorkPhone.
  Surround with Choice moves the element's current mappings into the first [When].
- the reference mapper cardinality marks (`?` optional, `*` repeating, `+` repeating & required), italic = unmapped,
  red = mandatory but unmapped / statement missing its formula.
- Right-click a target row: Edit, Expand ▸, Show Connected, Statement ▸ (Surround with Choice / If /
  For-Each, Copy-Of, Add When, Add/Remove Otherwise, Move up/down, Remove), Copy / Paste formula,
  Clear, Field ▸ (mandatory, add child, rename, delete). Toolbar: ⬆ ⬇ ✕ For-Each Choice +When If Copy-Of.
- Right-click a source field: Map to selected target, Show where used, Copy XPath / relative path.
- Drag a source container onto a target container: for-each (if both repeat) + children mapped by
  name with relative paths (pain.001.001.03 PmtInf → .06 PmtInf maps 595 fields in one drop).

## XPath Mapping Builder (centre)
- Tabs: Data (current for-each item first, then each source), Functions (grouped, with help),
  Variables (use + manage), Constants. Click or drag into the formula.
- Shows the evaluation context, validates the formula live and shows the XSLT it compiles to,
  plus the generated XSLT for the selected element.

## Formula language is now XPath-style
- Paths: `Name/FullName` (relative to the current for-each item), `../X`, `.`, `$s1/Document/...`,
  `/Document/...`; operators `= != < <= > >= and or + - * div mod`; XPath functions
  (`count`, `position`, `last`, `sum`, `concat`, `substring`, `string-length`, `normalize-space`,
  `translate`, `contains`, `starts-with`, `not`, `round`, …). Old `{0}` / UPPERCASE(...) formulas still work.
- `substring` now uses XPath semantics (1-based start, length).

## Engine fixes
- XSD `xs:choice` alternatives are optional (no more empty `<IBAN/>` + `<Othr/>` together).
- Optional containers holding a for-each are only written when the loop has items.

---

# Changes —  mapping logic, real XSLT testing, LLM fixes

Run `pip install -r backend/requirements.txt` (adds `anthropic`, `python-dotenv`, `lxml`), restart uvicorn.

## Mapping logic (centre panel)
- Centre shows only the selected target's logic; "☰ All mappings" is a toggle.
- Click any target node — field, container or root element — to see/edit its logic.
  Containers list the mapping logic inside them. Clicking a source field lists where it's used.
- **Surround with** `for-each`, `if`, `choose · when / otherwise`, `copy-of` on any node.
  Statements nest in any order (↑/↓ to reorder), e.g. for-each › choose › element.
  On a field, each `when`/`otherwise` can give its own value.
- Drag a source container onto a target container: repeating→repeating becomes a for-each
  and children are mapped by name (recursively).
- Source→target mapping lines (All / Selected / Off); badges on target tree nodes.
- Live generated-XSLT preview for the selected element.
- New DSL functions: AND, OR, NOT, EXISTS, ISEMPTY, CURRENTDATETIME('tz').

## XSLT generator (rewritten: backend/app/services/xslt_gen.py)
- Real XPath with XSD namespaces (`/s1:Document/s1:...`), target namespace on output.
- Paths inside a for-each are relative to the current item.
- Optional containers/fields are only written when their source exists.
- copy-of re-namespaces elements when source/target namespaces differ (pain.001.03 → .06).

## Test / Run
- Dropdown: "Generated XSLT (executed)" — runs the XSLT tab's stylesheet with lxml;
  "Generated processor rules (evaluated)" — same rules, any source format.
  Both produce identical output on the pain.001.001.03 → .06 sample.

## LLM
- Built-in provider uses the Anthropic SDK (default model claude-opus-5-5) and reads
  `ANTHROPIC_API_KEY` from `backend/.env`. Custom URLs accept a base URL.
- "Test connection" no longer fails on a non-JSON reply; network/auth errors are reported clearly.

## Known limits
- XML attributes (e.g. `Ccy="EUR"`) aren't modeled by the XSD parser, so they aren't mapped.
- MapStruct processor: leaf-level if/choose compile into expressions; for-each and statements
  on containers are listed as TODO comments (the XSLT implements them fully).

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

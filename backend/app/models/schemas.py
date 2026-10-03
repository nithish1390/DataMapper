"""
Pydantic models shared across the MapSheet AI API.

These mirror the shapes the Angular frontend works with directly, so the
frontend's TypeScript interfaces (see frontend/src/app/core/models) are a
straight 1:1 port of these.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SourceFormat = Literal[
    "jsonschema", "jsonobject", "xsd", "xml", "csv", "fixed", "swift", "pojo"
]
VarType = Literal["string", "integer", "number", "boolean", "date", "dateTime", "node"]
FieldType = Literal["string", "integer", "number", "boolean", "object", "array"]


class FieldNode(BaseModel):
    """One node in a parsed schema tree (leaf or container)."""

    name: str
    path: str
    type: FieldType
    mandatory: bool = False
    children: list["FieldNode"] = Field(default_factory=list)
    choice: Optional[str] = None  # xs:choice group id when this element is one alternative
    start: Optional[int] = None   # fixed width: 1-based start position
    length: Optional[int] = None  # fixed width: field length


FieldNode.model_rebuild()


class ParseRequest(BaseModel):
    format: SourceFormat
    text: str
    # CSV: 1-based line of the column names; 0 = no header row; None = detect
    csv_header_row: Optional[int] = None


class ParseResponse(BaseModel):
    tree: list[FieldNode]
    schema_name: Optional[str] = None
    field_count: int = 0
    namespace: Optional[str] = None  # XSD targetNamespace / XML sample root namespace
    format: Optional[str] = None     # the format actually used (may differ from the one chosen)
    note: Optional[str] = None       # e.g. "Looks like JSON sample, not JSON Schema — parsed as JSON sample."
    # choice group -> alternative present in the parsed message (e.g. SWIFT 50F out of 50A / 50F / 50K)
    choice_defaults: dict[str, str] = Field(default_factory=dict)
    csv_header_row: Optional[int] = None  # CSV: the header line used (detected or as given)


class SourceRef(BaseModel):
    """Points at one field on one named source."""

    source_id: str
    path: str


class MappingRule(BaseModel):
    id: str
    target: str
    inputs: list[SourceRef] = Field(default_factory=list)
    transform: str = ""
    for_each: bool = False  # legacy: same as a for-each statement over inputs[0]
    mode: Literal["value", "copy-of"] = "value"
    # Which choose-branch this mapping belongs to ("<statementId>:<branchId>"); "" = everywhere.
    scope: str = ""
    origin: Literal["manual", "ai", "sheet"] = "manual"
    confidence: Optional[str] = None
    note: Optional[str] = None


class VariableRule(BaseModel):
    id: str
    name: str
    inputs: list[SourceRef] = Field(default_factory=list)
    transform: str = ""
    var_type: VarType = "string"


StatementKind = Literal["for-each", "for-each-group", "if", "choose", "variable"]


class ChooseBranch(BaseModel):
    id: str = ""
    test: str = ""
    # Leaf targets only: the value for this branch. "" = use the field's own mapping.
    value: str = ""


class Statement(BaseModel):
    """An XSLT-style instruction wrapped around a target node (visual-mapper
    style). {0}, {1}... in test/value refer to this statement's own inputs."""

    id: str
    kind: StatementKind
    inputs: list[SourceRef] = Field(default_factory=list)
    select: str = ""                                 # for-each / for-each-group (formula path); falls back to inputs[0]
    group_by: str = ""                               # for-each-group (XSLT 2.0): grouping key formula
    name: str = ""                                   # variable: its name (used as $name)
    var_type: VarType = "string"                     # variable: data type
    test: str = ""                                   # if
    whens: list[ChooseBranch] = Field(default_factory=list)  # choose
    otherwise: Optional[str] = None                  # choose: None = no branch, "" = field mapping


class TargetStructure(BaseModel):
    target: str
    scope: str = ""
    statements: list[Statement] = Field(default_factory=list)  # outermost first


class RootCondition(BaseModel):
    inputs: list[SourceRef] = Field(default_factory=list)
    transform: str = ""


class SourceSpec(BaseModel):
    id: str
    label: str
    type: SourceFormat
    fields: list[FieldNode] = Field(default_factory=list)
    namespace: Optional[str] = None
    # choice group -> alternative the user is working with (display only: all stay mappable)
    choice_selections: dict[str, str] = Field(default_factory=dict)
    csv_header_row: Optional[int] = None  # CSV: line of the column names (0 = none, None = detect)


class TargetSpec(BaseModel):
    type: SourceFormat
    fields: list[FieldNode] = Field(default_factory=list)
    namespace: Optional[str] = None
    # xs:choice group id -> path of the alternative the user picked
    choice_selections: dict[str, str] = Field(default_factory=dict)
    mandatory_overrides: dict[str, bool] = Field(default_factory=dict)
    # SWIFT MT targets: write the result as MT text ("swift", the default) or as XML ("xml")
    # SWIFT MT / fixed-width targets: as text (the default: "swift" / "fixed") or as XML ("xml")
    output_format: Optional[Literal["swift", "fixed", "xml"]] = None
    csv_header_row: Optional[int] = None


class ProjectSettings(BaseModel):
    group: str = "com.example"
    artifact: str = "schema-mapper"
    package: str = "com.example.schemamapper"
    java_version: str = "21"
    boot_version: str = "3.3.4"
    dep_web: bool = True
    dep_lombok: bool = True
    dep_camel: bool = False
    dep_jackson: bool = True
    xslt_version: Literal["1.0", "2.0"] = "2.0"  # generated stylesheet + the processor used to test it


class JarFunction(BaseModel):
    class_name: str
    method_name: str
    params: list[str] = Field(default_factory=list)
    ret: str = "Object"
    group: str = ""  # user-chosen library name (Functions tab grouping)


class CustomSource(BaseModel):
    """An uploaded .java custom-function class, shipped inside the generated project."""

    file_name: str
    content: str


class FunctionLibraryUpload(BaseModel):
    kind: Literal["jar", "java"]
    file_name: str
    classes: list[str]
    functions: list[JarFunction]
    source: Optional[str] = None  # .java text, so the project download can include it


class MappingWorkspace(BaseModel):
    """The full state needed to generate code, run a test, or validate."""

    sources: list[SourceSpec]
    target: TargetSpec
    mappings: list[MappingRule]
    variables: list[VariableRule] = Field(default_factory=list)
    root_condition: RootCondition = Field(default_factory=RootCondition)
    structures: list[TargetStructure] = Field(default_factory=list)
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    jar_functions: list[JarFunction] = Field(default_factory=list)
    custom_sources: list[CustomSource] = Field(default_factory=list)
    custom_jars: list[str] = Field(default_factory=list)  # uploaded jar file names (for the README)


class CodegenResponse(BaseModel):
    processor_java: str
    xslt: str
    custom_functions_java: Optional[str] = None


class TestRunRequest(BaseModel):
    workspace: MappingWorkspace
    sample_inputs: dict[str, str]  # sourceId -> raw sample text
    output_format: Literal["json", "xml"] = "json"
    engine: Literal["processor", "xslt"] = "processor"


class TestRunResponse(BaseModel):
    output: str
    engine: str = "processor"
    warnings: list[str] = Field(default_factory=list)


class SnippetRequest(BaseModel):
    workspace: MappingWorkspace
    target: str
    scope: str = ""


class FormulaCheckRequest(BaseModel):
    workspace: MappingWorkspace
    text: str
    target: str = ""
    scope: str = ""
    outer: bool = False  # evaluate in the target's *outer* context (e.g. its own for-each select)


class FormulaCheckResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    xpath: str = ""
    context: str = ""


class RowProblem(BaseModel):
    row_key: str
    target: str
    message: str


class MappingAnalysis(BaseModel):
    links: list["MappingLink"]
    problems: list[RowProblem]


class MappingLink(BaseModel):
    source_id: str
    source_path: str           # tree path in the source (with [] markers)
    target: str                # target element path
    scope: str = ""
    row_key: str               # matches the target tree row in the UI
    kind: str                  # value-of | copy-of | for-each | if | when


class SnippetResponse(BaseModel):
    xslt: str
    java: str = ""


class ValidationIssue(BaseModel):
    target: str
    message: str
    severity: Literal["error", "warning"] = "warning"


class ValidationResponse(BaseModel):
    mapped_count: int
    total_count: int
    unmapped_mandatory: list[str]
    unmapped_optional: list[str]
    issues: list[ValidationIssue]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LlmHeader(BaseModel):
    name: str = ""
    value: str = ""


class LlmProviderConfig(BaseModel):
    provider: Literal["openai", "custom", "anthropic"] = "openai"  # kept for older clients; always OpenAI-compatible
    custom_url: Optional[str] = None
    custom_key: Optional[str] = None
    custom_model: Optional[str] = None
    # Extra HTTP headers for the custom endpoint (gateway keys, tenant ids, api-version, ...).
    # They override the defaults, e.g. a custom Authorization replaces the Bearer token.
    custom_headers: list[LlmHeader] = Field(default_factory=list)


class ChatRequest(BaseModel):
    workspace: MappingWorkspace
    instruction: str
    llm: LlmProviderConfig = Field(default_factory=LlmProviderConfig)


class ChatAction(BaseModel):
    op: Literal["add", "remove"] = "add"
    target: str
    inputs: list[SourceRef] = Field(default_factory=list)
    transform: str = ""


class ChatResponse(BaseModel):
    message: str
    actions: list[ChatAction] = Field(default_factory=list)


class SheetImportRow(BaseModel):
    source_hint: Optional[str] = None
    source_path: Optional[str] = None
    target_path: str
    transform: Optional[str] = None


class CatalogFunction(BaseModel):
    """One built-in function as the Mapping Builder offers it (sent so the AI uses exactly these)."""

    group: str = ""
    name: str
    template: str = ""
    desc: str = ""


class SheetImportRequest(BaseModel):
    workspace: MappingWorkspace
    rows: list[SheetImportRow]
    llm: LlmProviderConfig = Field(default_factory=LlmProviderConfig)
    functions: list[CatalogFunction] = Field(default_factory=list)


class SheetRowReport(BaseModel):
    """How one sheet row was mapped: by the rule parser, by the AI, or left for review."""

    target: str
    source: str = ""
    rule: str = ""
    formula: str = ""
    method: Literal["rule", "ai", "review"] = "rule"
    note: str = ""


class SheetImportResult(BaseModel):
    mappings: list[MappingRule]
    target_fields_added: list[FieldNode]
    notes: list[str]
    structures: list["TargetStructure"] = Field(default_factory=list)  # For-Each added for repeating targets
    report: list[SheetRowReport] = Field(default_factory=list)


class SheetPreview(BaseModel):
    sheet_names: list[str] = Field(default_factory=list)
    rows: list[list[str]]


MappingAnalysis.model_rebuild()


class FullValidationRequest(BaseModel):
    workspace: MappingWorkspace
    target_xsd: Optional[str] = None           # the target schema text, for validating the output
    source_xsd: Optional[str] = None           # source 1 schema text, for validating the sample input
    sample_inputs: dict[str, str] = Field(default_factory=dict)


class XsdErrorDetail(BaseModel):
    line: int = 0
    message: str                                # the schema validator's message, namespaces shortened
    target: str = ""                            # target field path it is about (if found)
    formula: str = ""                           # that field's mapping formula
    hint: str = ""                              # what is probably wrong / what to do


class XsdCheck(BaseModel):
    ran: bool = False
    valid: bool = False
    reason: str = ""                            # why it didn't run, if it didn't
    engine: str = ""
    errors: list[str] = Field(default_factory=list)
    details: list[XsdErrorDetail] = Field(default_factory=list)
    output: str = ""
    # the Test / Run sample checked against the source XSD (bad input explains many output errors)
    source_checked: bool = False
    source_valid: bool = True
    source_errors: list[str] = Field(default_factory=list)


class FullValidationResponse(BaseModel):
    valid: bool
    total_fields: int
    mapped_fields: int
    unmapped_mandatory: list[str]
    unmapped_optional: list[str]
    problems: list[RowProblem]
    xsd: XsdCheck

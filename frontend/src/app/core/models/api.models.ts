export type SourceFormat = 'jsonschema' | 'jsonobject' | 'xsd' | 'xml' | 'csv' | 'fixed' | 'swift' | 'pojo';
export type FieldType = 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array';

export interface FieldNode {
  name: string;
  path: string;
  type: FieldType;
  mandatory: boolean;
  children: FieldNode[];
  /** xs:choice group id when this element is one alternative of a choice. */
  choice?: string | null;
  /** Fixed width: 1-based start position and length. */
  start?: number | null;
  length?: number | null;
}

export interface SourceRef {
  source_id: string;
  path: string;
}

export interface MappingRule {
  id: string;
  target: string;
  inputs: SourceRef[];
  transform: string;
  for_each: boolean;
  mode?: 'value' | 'copy-of';
  /** Choose-branch this mapping belongs to ("<statementId>:<branchId>"); '' = everywhere. */
  scope?: string;
  origin: 'manual' | 'ai' | 'sheet';
  confidence?: string | null;
  note?: string | null;
}

export interface VariableRule {
  id: string;
  name: string;
  inputs: SourceRef[];
  transform: string;
  var_type?: VarType;
}

export type StatementKind = 'for-each' | 'for-each-group' | 'if' | 'choose' | 'variable';
export type VarType = 'string' | 'integer' | 'number' | 'boolean' | 'date' | 'dateTime' | 'node';

export interface ChooseBranch {
  id: string;
  test: string;
  /** Leaf targets only; '' = use the field's own mapping. */
  value: string;
}

/** An XSLT-style instruction wrapped around a target node (visual-mapper style).
 * {0}, {1}… in test/value refer to this statement's own inputs. */
export interface Statement {
  id: string;
  kind: StatementKind;
  inputs: SourceRef[];
  /** for-each / for-each-group: the repeating source path (formula). */
  select: string;
  /** for-each-group (XSLT 2.0): the grouping key, evaluated per item. */
  group_by?: string;
  /** variable: name ($name) and data type. */
  name?: string;
  var_type?: VarType;
  test: string;
  whens: ChooseBranch[];
  /** choose only: null = no otherwise branch, '' = field mapping, else an expression. */
  otherwise: string | null;
}

export interface TargetStructure {
  target: string;
  scope: string;
  /** Outermost first. */
  statements: Statement[];
}

export interface RootCondition {
  inputs: SourceRef[];
  transform: string;
}

export interface SourceSpec {
  id: string;
  label: string;
  type: SourceFormat;
  fields: FieldNode[];
  namespace?: string | null;
  /** choice group -> alternative the user picked (e.g. SWIFT 50F out of 50A / 50F / 50K). */
  choice_selections?: Record<string, string>;
  /** CSV: line of the column names (0 = no header row, null = auto-detect). */
  csv_header_row?: number | null;
}

export interface TargetSpec {
  type: SourceFormat;
  fields: FieldNode[];
  namespace?: string | null;
  mandatory_overrides: Record<string, boolean>;
  /** xs:choice group id -> path of the alternative the user picked. */
  choice_selections?: Record<string, string>;
  /** SWIFT MT targets: MT text (default) or XML. */
  /** SWIFT MT / fixed-width targets: as text (default) or as XML. */
  output_format?: 'swift' | 'fixed' | 'xml' | null;
  /** CSV: line of the column names (0 = no header row, null = auto-detect). */
  csv_header_row?: number | null;
}

export interface ProjectSettings {
  group: string;
  artifact: string;
  package: string;
  java_version: string;
  boot_version: string;
  dep_web: boolean;
  dep_lombok: boolean;
  dep_camel: boolean;
  dep_jackson: boolean;
  /** Generated stylesheet version; also picks the processor used by Test / Run. */
  xslt_version?: '1.0' | '2.0';
}

export interface JarFunction {
  class_name: string;
  method_name: string;
  params: string[];
  ret: string;
  group?: string;
}

export interface CustomSource {
  file_name: string;
  content: string;
}

/** An uploaded .jar or .java of custom functions, shown as one group in the Functions tab. */
export interface FunctionLibrary {
  id: string;
  name: string;
  kind: 'jar' | 'java';
  file_name: string;
  classes: string[];
  functions: JarFunction[];
  source?: string | null;
}

export interface FunctionLibraryUpload {
  kind: 'jar' | 'java';
  file_name: string;
  classes: string[];
  functions: JarFunction[];
  source?: string | null;
}

export interface MappingWorkspace {
  sources: SourceSpec[];
  target: TargetSpec;
  mappings: MappingRule[];
  variables: VariableRule[];
  root_condition: RootCondition;
  structures: TargetStructure[];
  project: ProjectSettings;
  jar_functions: JarFunction[];
  custom_sources: CustomSource[];
  custom_jars: string[];
}

export interface ParseResponse {
  tree: FieldNode[];
  schema_name?: string | null;
  field_count: number;
  namespace?: string | null;
  /** Format actually used — the content may have been detected as another format. */
  format?: SourceFormat;
  note?: string | null;
  /** choice group -> alternative present in the parsed message (pre-selected). */
  choice_defaults?: Record<string, string>;
  /** CSV: the header line the parse used (detected or as given). */
  csv_header_row?: number | null;
}

export interface CodegenResponse {
  processor_java: string;
  xslt: string;
  custom_functions_java?: string | null;
}

export interface ValidationIssue {
  target: string;
  message: string;
  severity: 'error' | 'warning';
}

export interface ValidationResponse {
  mapped_count: number;
  total_count: number;
  unmapped_mandatory: string[];
  unmapped_optional: string[];
  issues: ValidationIssue[];
}

export interface LlmProviderConfig {
  provider: 'openai';
  custom_url?: string | null;
  custom_key?: string | null;
  custom_model?: string | null;
  /** Extra HTTP headers sent to the custom endpoint; they override the defaults. */
  custom_headers?: { name: string; value: string }[];
}

export interface ChatAction {
  op: 'add' | 'remove';
  target: string;
  inputs: SourceRef[];
  transform: string;
}

export interface ChatResponse {
  message: string;
  actions: ChatAction[];
}

export interface ChatDisplayMessage {
  role: 'user' | 'assistant';
  text: string;
  actions?: ChatAction[];
  applied?: boolean;
}

export interface SheetImportRow {
  source_hint?: string | null;
  source_path?: string | null;
  target_path: string;
  transform?: string | null;
}

export interface SheetImportResult {
  mappings: MappingRule[];
  target_fields_added: FieldNode[];
  notes: string[];
}

export interface SheetPreview {
  sheet_names: string[];
  rows: string[][];
}

export type TestEngine = 'processor' | 'xslt';

export interface TestRunResponse {
  output: string;
  engine: TestEngine;
  warnings: string[];
}

export interface SnippetResponse {
  xslt: string;
  java: string;
}

export interface MappingLink {
  source_id: string;
  source_path: string;
  target: string;
  scope: string;
  row_key: string;
  kind: string;
}

export interface FormulaCheck {
  ok: boolean;
  error?: string | null;
  xpath: string;
  context: string;
}

export interface RowProblem {
  row_key: string;
  target: string;
  message: string;
}

export interface MappingAnalysis {
  links: MappingLink[];
  problems: RowProblem[];
}

export interface XsdErrorDetail {
  line: number;
  message: string;
  target: string;
  formula: string;
  hint: string;
}

export interface XsdCheck {
  ran: boolean;
  valid: boolean;
  reason: string;
  engine: string;
  errors: string[];
  details?: XsdErrorDetail[];
  output: string;
  source_checked?: boolean;
  source_valid?: boolean;
  source_errors?: string[];
}

export interface FullValidation {
  valid: boolean;
  total_fields: number;
  mapped_fields: number;
  unmapped_mandatory: string[];
  unmapped_optional: string[];
  problems: RowProblem[];
  xsd: XsdCheck;
}

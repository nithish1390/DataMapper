import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  ChatAction, ChatResponse, FormulaCheck, FullValidation, FunctionLibraryUpload, MappingAnalysis, MappingLink, CodegenResponse, FieldNode, JarFunction, LlmProviderConfig,
  MappingWorkspace, ParseResponse, SheetImportResult, SheetImportRow, SheetPreview,
  SnippetResponse, SourceFormat, TestEngine, TestRunResponse, ValidationResponse,
} from '../models/api.models';

/** Thin, fully-typed wrapper around every backend route. Nothing else in the
 * app talks to HttpClient directly. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = '/api';

  constructor(private http: HttpClient) {}

  parse(format: SourceFormat, text: string, csvHeaderRow: number | null = null): Observable<ParseResponse> {
    return this.http.post<ParseResponse>(`${this.base}/parse`, { format, text, csv_header_row: csvHeaderRow });
  }

  codegenPreview(workspace: MappingWorkspace): Observable<CodegenResponse> {
    return this.http.post<CodegenResponse>(`${this.base}/codegen/preview`, workspace);
  }

  validate(workspace: MappingWorkspace): Observable<ValidationResponse> {
    return this.http.post<ValidationResponse>(`${this.base}/codegen/validate`, workspace);
  }

  downloadProject(workspace: MappingWorkspace): Observable<Blob> {
    return this.http.post(`${this.base}/codegen/project`, workspace, { responseType: 'blob' });
  }

  snippet(workspace: MappingWorkspace, target: string, scope = ''): Observable<SnippetResponse> {
    return this.http.post<SnippetResponse>(`${this.base}/codegen/snippet`, { workspace, target, scope });
  }

  links(workspace: MappingWorkspace): Observable<MappingLink[]> {
    return this.http.post<MappingLink[]>(`${this.base}/codegen/links`, workspace);
  }

  validateFull(workspace: MappingWorkspace, targetXsd: string, sampleInputs: Record<string, string>,
               sourceXsd = ''): Observable<FullValidation> {
    return this.http.post<FullValidation>(`${this.base}/codegen/validate-full`,
      { workspace, target_xsd: targetXsd, source_xsd: sourceXsd, sample_inputs: sampleInputs });
  }

  analysis(workspace: MappingWorkspace): Observable<MappingAnalysis> {
    return this.http.post<MappingAnalysis>(`${this.base}/codegen/analysis`, workspace);
  }

  uploadFunctions(file: File): Observable<FunctionLibraryUpload> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<FunctionLibraryUpload>(`${this.base}/functions/upload`, form);
  }

  checkFormula(workspace: MappingWorkspace, text: string, target: string, outer: boolean): Observable<FormulaCheck> {
    return this.http.post<FormulaCheck>(`${this.base}/codegen/check-formula`, { workspace, text, target, outer });
  }

  testRun(workspace: MappingWorkspace, sampleInputs: Record<string, string>,
          outputFormat: 'json' | 'xml', engine: TestEngine): Observable<TestRunResponse> {
    return this.http.post<TestRunResponse>(`${this.base}/test-run`, {
      workspace, sample_inputs: sampleInputs, output_format: outputFormat, engine,
    });
  }

  testLlm(llm: LlmProviderConfig): Observable<{ ok: boolean; reply: string }> {
    return this.http.post<{ ok: boolean; reply: string }>(`${this.base}/chat/test`, llm);
  }

  chat(workspace: MappingWorkspace, instruction: string, llm: LlmProviderConfig): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${this.base}/chat`, { workspace, instruction, llm });
  }

  uploadJar(file: File): Observable<JarFunction[]> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<JarFunction[]>(`${this.base}/jar/upload`, form);
  }

  previewSheet(file: File, sheetName?: string): Observable<SheetPreview> {
    const form = new FormData();
    form.append('file', file);
    const params: Record<string, string> = sheetName ? { sheet_name: sheetName } : {};
    return this.http.post<SheetPreview>(`${this.base}/sheet/preview`, form, { params });
  }

  applySheet(workspace: MappingWorkspace, rows: SheetImportRow[],
             llm: LlmProviderConfig): Observable<SheetImportResult> {
    return this.http.post<SheetImportResult>(`${this.base}/sheet/apply`, { workspace, rows, llm });
  }
}

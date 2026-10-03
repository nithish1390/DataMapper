import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { SheetImportRow, SheetRowReport } from '../../../../core/models/api.models';
import { functionCatalog } from '../../../../core/models/function-catalog';

@Component({
  selector: 'app-sheet-import-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './sheet-import-modal.component.html',
})
export class SheetImportModalComponent {
  open = signal(false);
  file: File | null = null;
  sheetNames = signal<string[]>([]);
  selectedSheet = '';
  rows = signal<string[][]>([]);
  headerRow = 1;

  colSource = -1;
  colSourcePath = -1;
  colTargetPath = -1;
  colTransform = -1;
  /** After applying: how each row was mapped (shown until the dialog is closed). */
  report = signal<SheetRowReport[]>([]);
  applying = signal(false);
  reportFilter: 'all' | 'ai' | 'review' = 'all';

  get headers(): string[] {
    return this.rows()[this.headerRow - 1] ?? [];
  }

  get dataRows(): string[][] {
    return this.rows().slice(this.headerRow);
  }

  get columnIndexes(): number[] {
    return this.headers.map((_, i) => i);
  }

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
  ) {}

  show(): void {
    this.open.set(true);
  }

  shownReport(): SheetRowReport[] {
    return this.reportFilter === 'all' ? this.report() : this.report().filter((r) => r.method === this.reportFilter);
  }

  count(method: SheetRowReport['method']): number {
    return this.report().filter((r) => r.method === method).length;
  }

  goTo(target: string): void {
    this.reset();
    this.workspace.revealTarget(target);
  }

  reset(): void {
    this.open.set(false);
    this.report.set([]);
    this.applying.set(false);
    this.file = null;
    this.sheetNames.set([]);
    this.rows.set([]);
    this.headerRow = 1;
    this.colSource = this.colSourcePath = this.colTargetPath = this.colTransform = -1;
  }

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const f = input.files?.[0];
    if (!f) return;
    this.file = f;
    this.loadPreview();
  }

  loadPreview(sheetName?: string): void {
    if (!this.file) return;
    this.api.previewSheet(this.file, sheetName).subscribe({
      next: (res) => {
        this.sheetNames.set(res.sheet_names);
        if (res.sheet_names.length) this.selectedSheet = sheetName ?? res.sheet_names[0];
        this.rows.set(res.rows);
        this.headerRow = 1;
        this.autoDetectColumns();
      },
      error: (err) => this.toast.show(`Could not read file: ${err.error?.detail ?? err.message}`, true),
    });
  }

  onSheetChange(name: string): void {
    this.selectedSheet = name;
    this.loadPreview(name);
  }

  autoDetectColumns(): void {
    this.headers.forEach((h, i) => {
      const lh = (h || '').toLowerCase();
      if (/source.*path|src.*path/.test(lh)) this.colSourcePath = i;
      else if (/target.*path|dest.*path/.test(lh)) this.colTargetPath = i;
      else if (/transform|function|logic|instruction/.test(lh)) this.colTransform = i;
      else if (/^source$|^src$/.test(lh)) this.colSource = i;
    });
  }

  downloadTemplate(): void {
    const firstSource = this.workspace.sources()[0]?.id ?? 's1';
    const csv = `source,sourcePath,targetPath,transform\n${firstSource},orderId,orderNumber,\n`;
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mapping-template.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  apply(): void {
    if (this.colTargetPath < 0) {
      this.toast.show('Pick the target-path column.', true);
      return;
    }
    const rows: SheetImportRow[] = this.dataRows
      .map((r) => ({
        source_hint: this.colSource >= 0 ? r[this.colSource] : undefined,
        source_path: this.colSourcePath >= 0 ? r[this.colSourcePath] : undefined,
        target_path: r[this.colTargetPath] ?? '',
        transform: this.colTransform >= 0 ? r[this.colTransform] : undefined,
      }))
      .filter((r) => r.target_path);

    this.applying.set(true);
    // imported sheets use XSLT 2.0, so the AI may use every function (2.0 ones included)
    const ws = { ...this.workspace.toWorkspace() };
    ws.project = { ...ws.project, xslt_version: '2.0' };
    this.api.applySheet(ws, rows, this.workspace.llm(), functionCatalog(true)).subscribe({
      next: (res) => {
        this.applying.set(false);
        this.workspace.mappings.set(res.mappings);
        if (res.structures?.length) this.workspace.structures.update((list) => [...list, ...res.structures!]);
        this.workspace.setXsltVersion('2.0');  // imported sheets default to XSLT 2.0
        this.workspace.requestAnalysis();
        const rep = res.report ?? [];
        const ai = rep.filter((r) => r.method === 'ai').length;
        const review = rep.filter((r) => r.method === 'review').length;
        this.toast.show(`Applied ${rep.length} row(s): ${rep.length - ai - review} by rule, ${ai} by AI` +
          (review ? `, ${review} need review.` : '.'), review > 0);
        this.reportFilter = review ? 'review' : 'all';
        this.report.set(rep);
        this.rows.set([]);
      },
      error: (err) => {
        this.applying.set(false);
        this.toast.show(`Import failed: ${err.error?.detail ?? err.message}`, true);
      },
    });
  }
}

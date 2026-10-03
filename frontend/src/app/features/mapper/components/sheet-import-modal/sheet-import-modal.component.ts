import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { SheetImportRow } from '../../../../core/models/api.models';

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

  reset(): void {
    this.open.set(false);
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

    this.api.applySheet(this.workspace.toWorkspace(), rows, this.workspace.llm()).subscribe({
      next: (res) => {
        this.workspace.mappings.set(res.mappings);
        this.workspace.setXsltVersion('2.0');  // imported sheets default to XSLT 2.0
        this.reset();
        this.toast.show(`Applied ${res.mappings.length} mapping(s) from sheet (XSLT 2.0).`);
        if (res.notes.length) {
          this.toast.show(`${res.notes.length} row(s) need a look — check the mapping notes.`, true);
        }
      },
      error: (err) => this.toast.show(`Import failed: ${err.error?.detail ?? err.message}`, true),
    });
  }
}

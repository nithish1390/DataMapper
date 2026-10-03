import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TargetMapperComponent } from '../target-mapper/target-mapper.component';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { SourceFormat } from '../../../../core/models/api.models';
import { ToastService } from '../../../../core/services/toast.service';
import { InputFileService } from '../../../../core/services/input-file.service';
import { CsvHeaderPickerComponent } from '../../../../shared/components/csv-header-picker/csv-header-picker.component';

const FORMATS: { value: SourceFormat; label: string }[] = [
  { value: 'jsonschema', label: 'JSON Schema' },
  { value: 'jsonobject', label: 'JSON sample' },
  { value: 'xsd', label: 'XSD' },
  { value: 'xml', label: 'XML sample' },
  { value: 'csv', label: 'CSV' },
  { value: 'fixed', label: 'Fixed width (layout definition)' },
  { value: 'swift', label: 'SWIFT MT' },
  { value: 'pojo', label: 'Java class / POJO' },
];

@Component({
  selector: 'app-target-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, TargetMapperComponent, CsvHeaderPickerComponent],
  templateUrl: './target-panel.component.html',
})
export class TargetPanelComponent {
  formats = FORMATS;
  pasteMode = false;
  pasteText = '';
  showLoader = signal(true);

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
    private inputFiles: InputFileService,
  ) {}

  /** Opens the current target schema / payload as editable text, to change and re-parse. */
  toggleEditor(): void {
    if (this.showLoader()) {
      this.showLoader.set(false);
      return;
    }
    this.pasteText = this.workspace.target().raw || this.pasteText;
    if (this.workspace.target().ready) this.pasteMode = true;
    this.showLoader.set(true);
  }

  /** Example shown in the editor for the fixed-width format. */
  fixedHint = 'Field       Start   Length   Type\n-----------------------------------\nAccountNo   1       10       String\nName        11      15       String\nAmount      26      11       Decimal\nCurrency    37      3        String';

  /** Uploaded Excel workbook: switch sheets without uploading again. */
  workbook: { file: File; sheets: string[]; sheet: string | null } | null = null;

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.loadFile(file);
  }

  private async loadFile(file: File, sheet?: string | null): Promise<void> {
    try {
      const res = await this.inputFiles.read(file, sheet);
      this.workbook = res.spreadsheet ? { file, sheets: res.sheets, sheet: res.sheet } : null;
      const fixed = this.workspace.target().type === 'fixed';
      this.workspace.patchTarget({ raw: res.text, ...(res.spreadsheet && !fixed ? { type: 'csv' as const } : {}) });
      this.pasteText = res.text;
      if (res.spreadsheet) {
        this.toast.show(`Excel workbook converted to ${fixed ? 'a layout definition' : 'CSV'}${res.sheet ? ` (sheet "${res.sheet}")` : ''}` +
          (fixed ? ' — parse it to get the fields.' : ' — check the header row, then parse.'));
      }
      if (sheet !== undefined && this.workspace.target().ready) this.parse();
    } catch (e) {
      this.toast.show((e as Error).message, true);
    }
  }

  pickSheet(sheet: string): void {
    if (this.workbook) this.loadFile(this.workbook.file, sheet);
  }

  parse(): void {
    const t = this.workspace.target();
    const text = this.pasteMode ? this.pasteText : t.raw;
    if (!text.trim()) {
      this.toast.show('Add a file or paste text first.', true);
      return;
    }
    this.api.parse(t.type, text, t.type === 'csv' ? t.csv_header_row ?? null : null).subscribe({
      next: (res) => {
        this.workspace.setTargetParsed(res.tree, res.namespace);
        this.workspace.patchTarget({ raw: text, csvDetected: res.csv_header_row ?? null,
          ...(res.format && res.format !== t.type ? { type: res.format } : {}) });
        this.showLoader.set(false);
        const n = this.workspace.flatten(res.tree).filter((x) => x.children.length === 0).length;
        this.toast.show(res.note ? `${res.note} ${n} field(s).` : `${n} field(s) parsed.`);
      },
      error: (err) => this.toast.show(`Could not parse: ${err.error?.detail ?? err.message}`, true),
    });
  }

  /** CSV header row changed: re-parse straight away when the fields are already loaded. */
  setHeaderRow(row: number | null): void {
    this.workspace.patchTarget({ csv_header_row: row });
    if (this.workspace.target().ready && this.csvText().trim()) this.parse();
  }

  csvText(): string {
    return (this.pasteMode ? this.pasteText : this.workspace.target().raw) || this.workspace.target().raw || '';
  }

  addRootField(): void {
    if (!this.workspace.target().ready) this.workspace.patchTarget({ ready: true });
    const path = this.workspace.addTargetField('');
    if (!path) return;
    const name = window.prompt('Field name:', 'newField');
    if (name && name !== 'newField' && !this.workspace.renameTargetField(path, name)) {
      this.toast.show('Field name must be a valid identifier (letters, numbers, underscore).', true);
    }
  }
}

import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FieldTreeComponent, DragPayload } from '../field-tree/field-tree.component';
import { CsvHeaderPickerComponent } from '../../../../shared/components/csv-header-picker/csv-header-picker.component';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { FieldNode, SourceFormat } from '../../../../core/models/api.models';
import { ToastService } from '../../../../core/services/toast.service';
import { InputFileService } from '../../../../core/services/input-file.service';
import { ContextMenuService } from '../../../../shared/components/context-menu/context-menu.component';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';

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
  selector: 'app-source-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, FieldTreeComponent, CsvHeaderPickerComponent],
  templateUrl: './source-panel.component.html',
})
export class SourcePanelComponent {
  formats = FORMATS;
  pasteMode: Record<string, boolean> = {};
  pasteText: Record<string, string> = {};
  showLoader: Record<string, boolean> = {};

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
    private inputFiles: InputFileService,
    private menu: ContextMenuService,
    private confirm: ConfirmService,
  ) {}

  addSource(): void {
    this.workspace.addSource();
  }

  async removeSource(id: string, event: Event): Promise<void> {
    event.stopPropagation();
    if (this.workspace.sources().length <= 1) {
      this.toast.show('At least one source is required.', true);
      return;
    }
    const label = this.workspace.sourceLabel(id);
    if (!(await this.confirm.ask(`Remove ${label} ($${id})? Mappings that read only from it are removed too.`))) return;
    this.workspace.removeSource(id);
  }

  togglePanel(id: string): void {
    const s = this.workspace.sources().find((x) => x.id === id);
    if (s) this.workspace.patchSource(id, { panelCollapsed: !s.panelCollapsed });
  }

  /** Example shown in the editor for the fixed-width format. */
  fixedHint = 'Field       Start   Length   Type\n-----------------------------------\nAccountNo   1       10       String\nName        11      15       String\nAmount      26      11       Decimal\nCurrency    37      3        String';

  /** Uploaded Excel workbook per source: switch sheets without uploading again. */
  workbook: Record<string, { file: File; sheets: string[]; sheet: string | null }> = {};

  onFile(id: string, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.loadFile(id, file);
  }

  private async loadFile(id: string, file: File, sheet?: string | null): Promise<void> {
    try {
      const res = await this.inputFiles.read(file, sheet);
      if (res.spreadsheet) {
        this.workbook[id] = { file, sheets: res.sheets, sheet: res.sheet };
        const fixed = this.workspace.sources().find((s) => s.id === id)?.type === 'fixed';
        this.workspace.patchSource(id, { raw: res.text, type: fixed ? 'fixed' : 'csv' });
        this.toast.show(`Excel workbook converted to ${fixed ? 'a layout definition' : 'CSV'}${res.sheet ? ` (sheet "${res.sheet}")` : ''}` +
          (fixed ? ' — parse it to get the fields.' : ' — check the header row, then parse.'));
      } else {
        delete this.workbook[id];
        this.workspace.patchSource(id, { raw: res.text });
      }
      this.pasteText[id] = res.text;  // editable right away under "Paste"
      const src = this.workspace.sources().find((s) => s.id === id);
      if (sheet !== undefined && src?.ready) this.parse(id);
    } catch (e) {
      this.toast.show((e as Error).message, true);
    }
  }

  pickSheet(id: string, sheet: string): void {
    const wb = this.workbook[id];
    if (wb) this.loadFile(id, wb.file, sheet);
  }

  parse(id: string): void {
    const src = this.workspace.sources().find((s) => s.id === id);
    if (!src) return;
    const text = this.pasteMode[id] ? this.pasteText[id] ?? '' : src.raw;
    if (!text.trim()) {
      this.toast.show('Add a file or paste text first.', true);
      return;
    }
    this.api.parse(src.type, text, src.type === 'csv' ? src.csv_header_row ?? null : null).subscribe({
      next: (res) => {
        this.workspace.setSourceParsed(id, res.tree, res.namespace);
        this.workspace.patchSource(id, {
          raw: text, ...(res.format && res.format !== src.type ? { type: res.format } : {}),
          choice_selections: res.choice_defaults ?? {}, csvDetected: res.csv_header_row ?? null,
        });
        this.showLoader[id] = false;
        const n = this.workspace.flatten(res.tree).filter((x) => x.children.length === 0).length;
        this.toast.show(res.note ? `${res.note} ${n} field(s).` : `${n} field(s) parsed.`);
      },
      error: (err) => this.toast.show(`Could not parse: ${err.error?.detail ?? err.message}`, true),
    });
  }

  /** CSV header row changed: re-parse straight away when the fields are already loaded. */
  setHeaderRow(id: string, row: number | null): void {
    this.workspace.patchSource(id, { csv_header_row: row });
    const src = this.workspace.sources().find((s) => s.id === id);
    if (src?.ready && (this.pasteMode[id] ? this.pasteText[id] : src.raw)?.trim()) this.parse(id);
  }

  csvText(id: string): string {
    const src = this.workspace.sources().find((s) => s.id === id);
    return (this.pasteMode[id] ? this.pasteText[id] : src?.raw) || src?.raw || '';
  }

  onNodeClick(sourceId: string, node: FieldNode): void {
    const current = this.workspace.selectedSource();
    const same = current?.source_id === sourceId && current?.path === node.path;
    this.workspace.selectedSource.set(same ? null : { source_id: sourceId, path: node.path });
    // Show this source field's usages in the centre panel.
    if (!same) this.workspace.detailTarget.set(null);
  }

  /** Opens the current schema / payload as editable text (pasted or uploaded), to change and re-parse. */
  toggleEditor(id: string): void {
    if (this.showLoader[id]) {
      this.showLoader[id] = false;
      return;
    }
    const src = this.workspace.sources().find((x) => x.id === id);
    this.pasteText[id] = src?.raw ?? this.pasteText[id] ?? '';
    this.pasteMode[id] = true;
    this.showLoader[id] = true;
    if (src?.panelCollapsed) this.workspace.patchSource(id, { panelCollapsed: false });
  }

  pickChoice(sourceId: string, e: { group: string; path: string }): void {
    const cur = this.workspace.sources().find((x) => x.id === sourceId)?.choice_selections?.[e.group];
    this.workspace.selectSourceChoice(sourceId, e.group, cur === e.path ? null : e.path);
  }

  mappedInputsFor(sourceId: string): Set<string> {
    const out = new Set<string>();
    this.workspace.links().forEach((l) => { if (l.source_id === sourceId) out.add(`${sourceId}::${l.source_path}`); });
    return out;
  }

  openMenu(sourceId: string, e: { node: FieldNode; event: MouseEvent }): void {
    const row = this.workspace.selectedRow();
    const ref = this.workspace.refFor(row, sourceId, e.node.path);
    const abs = this.workspace.refFor(null, sourceId, e.node.path);
    this.workspace.selectedSource.set({ source_id: sourceId, path: e.node.path });
    this.menu.open(e.event, [
      { label: `Map to selected target${row ? ' (' + row.label + ')' : ''}`, disabled: !row,
        action: () => {
          const msg = this.workspace.dropOnRow(row!, sourceId, e.node.path);
          if (msg) this.toast.show(msg);
        } },
      { label: 'Show where used', action: () => this.workspace.selectRow(null) },
      { separator: true },
      { label: 'Copy XPath', hint: abs, action: () => this.copy(abs) },
      { label: 'Copy relative path', hint: ref, disabled: ref === abs, action: () => this.copy(ref) },
    ]);
  }

  private copy(text: string): void {
    navigator.clipboard?.writeText(text).then(() => this.toast.show(`Copied ${text}`)).catch(() => undefined);
  }
}

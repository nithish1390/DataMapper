import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FieldTreeComponent, DragPayload } from '../field-tree/field-tree.component';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { FieldNode, SourceFormat } from '../../../../core/models/api.models';
import { ToastService } from '../../../../core/services/toast.service';
import { ContextMenuService } from '../../../../shared/components/context-menu/context-menu.component';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';

const FORMATS: { value: SourceFormat; label: string }[] = [
  { value: 'jsonschema', label: 'JSON Schema' },
  { value: 'jsonobject', label: 'JSON Object (sample)' },
  { value: 'xsd', label: 'XSD' },
  { value: 'csv', label: 'CSV' },
  { value: 'swagger', label: 'Swagger / OpenAPI' },
  { value: 'swift', label: 'SWIFT MT' },
  { value: 'pojo', label: 'Java class / POJO' },
];

@Component({
  selector: 'app-source-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, FieldTreeComponent],
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

  onFile(id: string, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    file.text().then((text) => this.workspace.patchSource(id, { raw: text }));
  }

  parse(id: string): void {
    const src = this.workspace.sources().find((s) => s.id === id);
    if (!src) return;
    const text = this.pasteMode[id] ? this.pasteText[id] ?? '' : src.raw;
    if (!text.trim()) {
      this.toast.show('Add a file or paste text first.', true);
      return;
    }
    this.api.parse(src.type, text).subscribe({
      next: (res) => {
        this.workspace.setSourceParsed(id, res.tree, res.namespace);
        this.workspace.patchSource(id, { raw: text });
        this.showLoader[id] = false;
        this.toast.show(`${this.workspace.flatten(res.tree).filter((n) => n.children.length === 0).length} field(s) parsed.`);
      },
      error: (err) => this.toast.show(`Could not parse: ${err.error?.detail ?? err.message}`, true),
    });
  }

  onNodeClick(sourceId: string, node: FieldNode): void {
    const current = this.workspace.selectedSource();
    const same = current?.source_id === sourceId && current?.path === node.path;
    this.workspace.selectedSource.set(same ? null : { source_id: sourceId, path: node.path });
    // Show this source field's usages in the centre panel.
    if (!same) this.workspace.detailTarget.set(null);
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

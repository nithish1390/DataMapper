import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TargetMapperComponent } from '../target-mapper/target-mapper.component';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { SourceFormat } from '../../../../core/models/api.models';
import { ToastService } from '../../../../core/services/toast.service';

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
  selector: 'app-target-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, TargetMapperComponent],
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
  ) {}

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    file.text().then((text) => this.workspace.patchTarget({ raw: text }));
  }

  parse(): void {
    const t = this.workspace.target();
    const text = this.pasteMode ? this.pasteText : t.raw;
    if (!text.trim()) {
      this.toast.show('Add a file or paste text first.', true);
      return;
    }
    this.api.parse(t.type, text).subscribe({
      next: (res) => {
        this.workspace.setTargetParsed(res.tree, res.namespace);
        this.workspace.patchTarget({ raw: text });
        this.showLoader.set(false);
        this.toast.show(`${this.workspace.flatten(res.tree).filter((n) => n.children.length === 0).length} field(s) parsed.`);
      },
      error: (err) => this.toast.show(`Could not parse: ${err.error?.detail ?? err.message}`, true),
    });
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

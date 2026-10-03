import { CommonModule } from '@angular/common';
import { Component, Injectable, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { newId } from '../../../../core/services/formula';
import { FunctionLibrary } from '../../../../core/models/api.models';

@Injectable({ providedIn: 'root' })
export class CustomFunctionsService {
  readonly isOpen = signal(false);

  open(): void {
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }
}

/** Upload .jar / .java custom-function libraries. Each library is one named
 * group in the Mapping Builder's Functions tab and can be renamed or removed. */
@Component({
  selector: 'app-custom-functions-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="modal-backdrop" *ngIf="svc.isOpen()" (click)="svc.close()">
      <div class="modal" style="width: 620px;" (click)="$event.stopPropagation()">
        <h2>Custom functions</h2>
        <div class="sub">
          Upload a <b>.jar</b> or a <b>.java</b> class. Its public static methods appear in the Mapping Builder's
          Functions tab, grouped under the name you give. Uploaded .java classes are added to the downloaded project.
        </div>

        <div class="cf-upload">
          <div style="flex: 1;">
            <label class="field-label" style="margin-top: 0;">Group name</label>
            <input type="text" [(ngModel)]="groupName" placeholder="e.g. Payment utils (defaults to the file name)">
          </div>
          <div>
            <label class="field-label" style="margin-top: 0;">&nbsp;</label>
            <button class="primary" [disabled]="busy()" (click)="file.click()">{{ busy() ? 'Reading…' : '⬆ Upload .jar / .java' }}</button>
            <input #file type="file" accept=".jar,.java" multiple style="display: none" (change)="onFiles($event)">
          </div>
        </div>

        <div *ngIf="!workspace.libraries().length" class="hint" style="margin-top: 14px;">No custom functions uploaded yet.</div>

        <div *ngFor="let lib of workspace.libraries()" class="cf-lib">
          <div class="cf-lib-head">
            <span class="tm-caret" (click)="toggle(lib.id)">{{ expanded().has(lib.id) ? '⊟' : '⊞' }}</span>
            <span class="kind-chip">{{ lib.kind }}</span>
            <input type="text" class="cf-name" [value]="lib.name" title="Group name shown in the Functions tab"
                   (change)="rename(lib, $any($event.target).value)">
            <span class="muted ellipsis" style="max-width: 180px;" [title]="lib.file_name">{{ lib.file_name }}</span>
            <span class="muted">{{ lib.functions.length }} fn · {{ lib.classes.length }} class(es)</span>
            <button class="ghost tiny danger-text" (click)="remove(lib)" title="Delete this library">🗑</button>
          </div>
          <div *ngIf="expanded().has(lib.id)" class="cf-fns">
            <div *ngFor="let f of lib.functions" class="mono" style="font-size: 11px;">
              {{ f.class_name.split('.').pop() }}.<b>{{ f.method_name }}</b>({{ f.params.join(', ') }}) : {{ f.ret }}
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button class="primary" (click)="svc.close()">Done</button>
        </div>
      </div>
    </div>
  `,
})
export class CustomFunctionsModalComponent {
  groupName = '';
  busy = signal(false);
  expanded = signal<Set<string>>(new Set());

  constructor(
    public svc: CustomFunctionsService,
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
    private confirm: ConfirmService,
  ) {}

  onFiles(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (!files.length) return;
    this.busy.set(true);
    let pending = files.length;
    const done = () => {
      pending -= 1;
      if (!pending) {
        this.busy.set(false);
        this.groupName = '';
      }
    };
    for (const file of files) {
      this.api.uploadFunctions(file).subscribe({
        next: (res) => {
          const base = file.name.replace(/\.(jar|java)$/i, '');
          const name = this.groupName.trim() ? (files.length > 1 ? `${this.groupName.trim()} · ${base}` : this.groupName.trim()) : base;
          const lib: FunctionLibrary = { id: newId('lib'), name, ...res };
          this.workspace.addLibrary(lib);
          this.toast.show(`${res.functions.length} function(s) from ${file.name} added under "${name}".`);
          done();
        },
        error: (err) => {
          this.toast.show(`${file.name}: ${err.error?.detail ?? err.message}`, true);
          done();
        },
      });
    }
  }

  rename(lib: FunctionLibrary, name: string): void {
    if (name.trim() && name !== lib.name) this.workspace.renameLibrary(lib.id, name.trim());
  }

  toggle(id: string): void {
    const next = new Set(this.expanded());
    next.has(id) ? next.delete(id) : next.add(id);
    this.expanded.set(next);
  }

  async remove(lib: FunctionLibrary): Promise<void> {
    if (await this.confirm.ask(
      `Delete the custom function library "${lib.name}" (${lib.file_name}, ${lib.functions.length} function(s))?\n` +
      'Formulas that use its functions will keep their text but generate TODO stubs.')) {
      this.workspace.removeLibrary(lib.id);
    }
  }
}

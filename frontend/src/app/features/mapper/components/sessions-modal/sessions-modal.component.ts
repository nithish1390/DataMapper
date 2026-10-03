import { CommonModule, DatePipe } from '@angular/common';
import { Component, Injectable, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { SessionService } from '../../../../core/services/session.service';
import { ToastService } from '../../../../core/services/toast.service';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';

@Injectable({ providedIn: 'root' })
export class SessionsModalService {
  readonly isOpen = signal(false);

  open(): void {
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }
}

/** Sessions: name the work, save it to a file in any state, open a saved file to continue,
 * start a new one, or restore what was auto-saved in this browser. */
@Component({
  selector: 'app-sessions-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  template: `
    <div class="modal-backdrop" *ngIf="ui.isOpen()" (click)="ui.close()">
      <div class="modal" style="width: 560px;" (click)="$event.stopPropagation()">
        <h2>Sessions</h2>
        <div class="sub">
          A session holds everything: sources and target (schemas), mappings and statements, variables,
          custom functions, Test / Run samples and settings. Save it as a file in any state and open it later
          to carry on exactly where you left off.
        </div>

        <label class="field-label" style="margin-top: 0;">Session name</label>
        <input type="text" [ngModel]="workspace.sessionName()" (ngModelChange)="workspace.sessionName.set($event)"
               placeholder="e.g. pain.001 v03 → v06 migration">
        <div class="hint">Saved as <code>{{ sessions.fileName() }}</code>
          <span *ngIf="workspace.unsaved()" class="unsaved-pill">● unsaved changes</span>
          <span *ngIf="!workspace.unsaved() && sessions.lastFileSave()" style="color: var(--success);">
            ✓ saved {{ sessions.lastFileSave() | date: 'HH:mm:ss' }}</span>
        </div>

        <label style="display: flex; align-items: center; gap: 6px; font-size: 11.5px; margin-top: 8px;">
          <input type="checkbox" style="width: auto;" [(ngModel)]="includeSecrets">
          Include the LLM API key and header values in the file
        </label>

        <div class="sess-actions">
          <button class="primary" (click)="save()">💾 Save session <span class="kbd">Ctrl/⌘ S</span></button>
          <button (click)="file.click()">📂 Open session…</button>
          <button class="ghost" (click)="newSession()">＋ New session</button>
          <input #file type="file" accept=".json,.mapsheet.json,.dmsession.json" style="display: none" (change)="open($event)">
        </div>

        <div class="sess-draft" *ngIf="sessions.draftInfo() as d">
          <div>
            <strong>Auto-saved in this browser</strong>
            <div class="muted">"{{ d.name }}" · {{ d.saved_at | date: 'd MMM y, HH:mm:ss' }}</div>
            <div class="muted" style="margin-top: 2px;">Written automatically a few seconds after each change and
              when the page is closed or reloaded.</div>
          </div>
          <div style="display: flex; gap: 6px; align-self: center;">
            <button class="small" (click)="restore()">Restore</button>
            <button class="ghost small danger-text" (click)="discard()">Discard</button>
          </div>
        </div>

        <div class="modal-actions">
          <button class="primary" (click)="ui.close()">Done</button>
        </div>
      </div>
    </div>
  `,
})
export class SessionsModalComponent {
  includeSecrets = false;

  constructor(
    public ui: SessionsModalService,
    public workspace: WorkspaceService,
    public sessions: SessionService,
    private toast: ToastService,
    private confirm: ConfirmService,
  ) {}

  save(): void {
    if (!this.workspace.sessionName().trim()) {
      this.toast.show('Give the session a name first.', true);
      return;
    }
    this.sessions.saveToFile(this.includeSecrets);
    this.toast.show(`Session saved as ${this.sessions.fileName()}.`);
  }

  async open(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    if (this.workspace.unsaved() && !(await this.confirm.ask(
      'Opening a session replaces everything currently loaded. Unsaved changes will be lost.',
      `Open ${file.name}?`, 'Yes, open it'))) return;
    try {
      const name = await this.sessions.openFile(file);
      this.toast.show(`Session "${name}" opened.`);
      this.ui.close();
    } catch (e) {
      this.toast.show((e as Error).message, true);
    }
  }

  async newSession(): Promise<void> {
    if (this.workspace.dirty() && !(await this.confirm.ask(
      'Start a new, empty session? Everything currently loaded is cleared' +
      (this.workspace.unsaved() ? ' and the unsaved changes are lost.' : '.'), 'New session', 'Yes, start new'))) return;
    this.workspace.resetSession();
    this.workspace.markSaved();
    this.toast.show('New session started.');
  }

  async restore(): Promise<void> {
    if (this.workspace.dirty() && !(await this.confirm.ask(
      'Restoring the auto-saved session replaces everything currently loaded.', 'Restore auto-saved session?',
      'Yes, restore'))) return;
    if (await this.sessions.restoreDraft()) {
      this.toast.show('Auto-saved session restored.');
      this.ui.close();
    }
  }

  async discard(): Promise<void> {
    if (await this.confirm.ask('Delete the session auto-saved in this browser?')) await this.sessions.discardDraft();
  }
}

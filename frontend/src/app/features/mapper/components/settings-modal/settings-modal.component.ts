import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { LlmProviderConfig, ProjectSettings } from '../../../../core/models/api.models';

@Component({
  selector: 'app-settings-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings-modal.component.html',
})
export class SettingsModalComponent {
  open = signal(false);
  testResult = signal<{ ok: boolean; message: string } | null>(null);
  testing = signal(false);

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
    private confirm: ConfirmService,
  ) {}

  // ------------------------------------------------------- custom headers
  showHeaderValues = false;
  trackIndex = (i: number) => i;

  headers(): { name: string; value: string }[] {
    return this.workspace.llm().custom_headers ?? [];
  }

  addHeader(): void {
    this.patchLlm({ custom_headers: [...this.headers(), { name: '', value: '' }] });
  }

  patchHeader(index: number, patch: Partial<{ name: string; value: string }>): void {
    this.patchLlm({ custom_headers: this.headers().map((h, i) => (i === index ? { ...h, ...patch } : h)) });
  }

  async removeHeader(index: number): Promise<void> {
    const h = this.headers()[index];
    if (h.name || h.value) {
      if (!(await this.confirm.ask(`Remove the header "${h.name || '(unnamed)'}"?`))) return;
    }
    this.patchLlm({ custom_headers: this.headers().filter((_, i) => i !== index) });
  }

  validName(name: string): boolean {
    return /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name.trim());
  }

  hasInvalidHeader(): boolean {
    return this.headers().some((h) => h.name.trim() && !this.validName(h.name));
  }

  show(): void {
    this.open.set(true);
  }

  close(): void {
    this.open.set(false);
  }

  patchProject(patch: Partial<ProjectSettings>): void {
    this.workspace.project.set({ ...this.workspace.project(), ...patch });
  }

  patchLlm(patch: Partial<LlmProviderConfig>): void {
    this.workspace.llm.set({ ...this.workspace.llm(), ...patch });
  }

  onGroupChange(value: string): void {
    this.patchProject({ group: value });
    this.syncPackage();
  }

  onArtifactChange(value: string): void {
    this.patchProject({ artifact: value });
    this.syncPackage();
  }

  syncPackage(): void {
    const p = this.workspace.project();
    const pkg = `${p.group || 'com.example'}.${(p.artifact || 'app').replace(/[^a-zA-Z0-9]/g, '').toLowerCase()}`;
    this.patchProject({ package: pkg });
  }


  testConnection(): void {
    this.testing.set(true);
    this.testResult.set(null);
    this.api.testLlm(this.workspace.llm()).subscribe({
      next: (res) => {
        this.testing.set(false);
        this.testResult.set({ ok: true, message: `✓ Reachable — model replied "${res.reply}".` });
      },
      error: (err) => {
        this.testing.set(false);
        this.testResult.set({ ok: false, message: `✕ ${err.error?.detail ?? err.message}` });
      },
    });
  }

  save(): void {
    this.open.set(false);
    this.toast.show('Settings saved.');
  }
}

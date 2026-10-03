import { CommonModule } from '@angular/common';
import { Component, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { TestEngine } from '../../../../core/models/api.models';

type Tab = 'processor' | 'xslt' | 'test';

@Component({
  selector: 'app-bottom-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './bottom-panel.component.html',
})
export class BottomPanelComponent {
  activeTab = signal<Tab>('processor');
  processorCode = signal('// Parse a source + target and add mappings to see generated code here.');
  xsltCode = signal('// Parse a source + target and add mappings to see generated XSLT here.');
  get sampleInputs(): Record<string, string> {
    return this.workspace.sampleInputs;
  }
  testOutput = signal('// click Run');
  testFormat: 'json' | 'xml' = 'xml';
  engine: TestEngine = 'xslt';
  running = signal(false);
  testError = signal(false);
  testWarnings = signal<string[]>([]);
  lastEngine = signal<TestEngine | null>(null);
  private refreshTimer?: ReturnType<typeof setTimeout>;

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
  ) {
    // Debounced live-refresh of the generated code whenever mappings/variables/etc change.
    effect(() => {
      // touch the signals we care about so this effect re-runs on change
      this.workspace.mappings();
      this.workspace.variables();
      this.workspace.rootCondition();
      this.workspace.structures();
      this.workspace.project();
      this.workspace.sources();
      this.workspace.target();
      clearTimeout(this.refreshTimer);
      this.refreshTimer = setTimeout(() => this.refreshCode(), 300);
    });
  }

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
  }

  refreshCode(): void {
    if (!this.workspace.anySourceReady() || !this.workspace.target().ready) return;
    this.api.codegenPreview(this.workspace.toWorkspace()).subscribe({
      next: (res) => {
        this.processorCode.set(res.processor_java);
        this.xsltCode.set(res.xslt);
      },
      error: () => { /* silent: keep last good preview while the workspace is mid-edit */ },
    });
  }

  copy(text: string): void {
    navigator.clipboard.writeText(text).then(() => this.toast.show('Copied.'));
  }

  runTest(): void {
    this.running.set(true);
    const engine = this.engine;
    this.api.testRun(this.workspace.toWorkspace(), this.sampleInputs, this.testFormat, engine).subscribe({
      next: (res) => {
        this.running.set(false);
        this.testError.set(false);
        this.lastEngine.set(engine);
        this.testWarnings.set(res.warnings ?? []);
        this.testOutput.set(res.output);
      },
      error: (err) => {
        this.running.set(false);
        this.testError.set(true);
        this.lastEngine.set(engine);
        this.testWarnings.set([]);
        this.testOutput.set(`✕ ${err.error?.detail ?? err.message}`);
      },
    });
  }
}

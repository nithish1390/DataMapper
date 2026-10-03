import { mappingSheet, toCsvText } from '../../../../core/services/mapping-export';
import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, OnInit, ViewChild, effect, signal } from '@angular/core';
import { SourcePanelComponent } from '../source-panel/source-panel.component';
import { TargetPanelComponent } from '../target-panel/target-panel.component';
import { FormulaBuilderComponent } from '../formula-builder/formula-builder.component';
import { ContextMenuComponent } from '../../../../shared/components/context-menu/context-menu.component';
import { ConfirmDialogComponent } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { CustomFunctionsModalComponent, CustomFunctionsService } from '../custom-functions-modal/custom-functions-modal.component';
import { SessionsModalComponent, SessionsModalService } from '../sessions-modal/sessions-modal.component';
import { SessionService } from '../../../../core/services/session.service';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { ThemePickerComponent } from '../../../../shared/components/theme-picker/theme-picker.component';
import { ValidationModalComponent, ValidationService } from '../validation-modal/validation-modal.component';
import { BottomPanelComponent } from '../bottom-panel/bottom-panel.component';
import { ChatDrawerComponent } from '../chat-drawer/chat-drawer.component';
import { SettingsModalComponent } from '../settings-modal/settings-modal.component';
import { SheetImportModalComponent } from '../sheet-import-modal/sheet-import-modal.component';
import { MappingLinesComponent } from '../mapping-lines/mapping-lines.component';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';

@Component({
  selector: 'app-mapper-page',
  standalone: true,
  imports: [
    CommonModule, SourcePanelComponent, TargetPanelComponent, FormulaBuilderComponent, ContextMenuComponent, ConfirmDialogComponent, CustomFunctionsModalComponent, ValidationModalComponent, ThemePickerComponent, SessionsModalComponent,
    BottomPanelComponent, ChatDrawerComponent, MappingLinesComponent, SettingsModalComponent, SheetImportModalComponent,
  ],
  templateUrl: './mapper-page.component.html',
})
export class MapperPageComponent implements OnInit {
  @ViewChild('railSource') railSource!: ElementRef<HTMLElement>;
  @ViewChild('railTarget') railTarget!: ElementRef<HTMLElement>;
  @ViewChild('bottomPanel') bottomPanel!: ElementRef<HTMLElement>;
  @ViewChild(SettingsModalComponent) settingsModal!: SettingsModalComponent;
  @ViewChild(SheetImportModalComponent) sheetModal!: SheetImportModalComponent;

  leftWidth = signal(300);
  rightWidth = signal(Math.max(480, Math.round(window.innerWidth * 0.36)));
  bottomHeight = signal(300);

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
    public customFns: CustomFunctionsService,
    private validation: ValidationService,
    public sessionsUi: SessionsModalService,
    private sessions: SessionService,
    private confirm: ConfirmService,
  ) {
    // Auto-save a draft of the session in this browser a few seconds after each change.
    effect(() => {
      this.workspace.sources(); this.workspace.target(); this.workspace.mappings(); this.workspace.structures();
      this.workspace.variables(); this.workspace.libraries(); this.workspace.sessionName();
      if (this.workspace.dirty()) this.sessions.scheduleDraft();
    });
  }

  /** Offer to restore the session auto-saved before the last reload / close. */
  async ngOnInit(): Promise<void> {
    const draft = await this.sessions.readDraft();
    if (!draft || this.workspace.dirty()) return;
    const when = new Date(draft.saved_at).toLocaleString();
    if (await this.confirm.ask(`"${draft.name}" was auto-saved in this browser on ${when}. Restore it?`,
      'Restore your last session?', 'Yes, restore')) {
      await this.sessions.load(draft);
      this.toast.show(`Session "${draft.name}" restored.`);
    }
  }

  /** Reload / close: save a draft in the browser and let the browser ask "Leave site?". Browsers
   * don't allow a custom dialog (or a file download) here, so use Sessions › Save for a file. */
  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent): void {
    if (!this.workspace.unsaved()) return;
    void this.sessions.saveDraft();
    event.preventDefault();
    event.returnValue = '';
  }

  /** Ctrl/⌘ + S saves the session to a file. */
  @HostListener('document:keydown', ['$event'])
  onKey(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      this.sessions.saveToFile(false);
      this.toast.show(`Session saved as ${this.sessions.fileName()}.`);
    }
  }

  // ------------------------------------------------------------ splitters
  startDragSplitter(event: MouseEvent, side: 'left' | 'right'): void {
    event.preventDefault();
    const startX = event.clientX;
    const startW = side === 'left' ? this.leftWidth() : this.rightWidth();
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      const next = Math.max(220, Math.min(side === 'left' ? 640 : 1100, side === 'left' ? startW + dx : startW - dx));
      side === 'left' ? this.leftWidth.set(next) : this.rightWidth.set(next);
      this.workspace.bumpLayout();
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  startDragBottom(event: MouseEvent): void {
    event.preventDefault();
    const startY = event.clientY;
    const startH = this.bottomHeight();
    const onMove = (ev: MouseEvent) => {
      const dy = ev.clientY - startY;
      const next = Math.max(90, Math.min(window.innerHeight - 200, startH - dy));
      this.bottomHeight.set(next);
      this.workspace.bumpLayout();
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // -------------------------------------------------------------- actions
  validate(): void {
    if (!this.workspace.target().ready) {
      this.toast.show('Parse a target first.', true);
      return;
    }
    this.validation.run();
  }

  /** Exports the mapping as it appears in the target tree: one row per mapped field, statement
   * (For-Each, Choice / When / Otherwise, If) and variable, with its formula, the source fields it
   * reads and the statements it sits in. */
  exportSheet(): void {
    const ws = this.workspace;
    const out = mappingSheet(ws);
    if (out.length === 1) {
      this.toast.show('No mappings to export yet.', true);
      return;
    }
    const csv = toCsvText(out);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const base = ws.sessionName().trim().replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'current';
    a.download = `${base}-mappings.csv`;
    a.click();
    URL.revokeObjectURL(url);
    this.toast.show(`Mapping sheet exported: ${out.length - 1} row(s).`);
  }

  downloadProject(): void {
    if (!this.workspace.sources().every((s) => s.ready) || !this.workspace.target().ready) {
      this.toast.show('Parse every source and the target before downloading.', true);
      return;
    }
    this.api.downloadProject(this.workspace.toWorkspace()).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.workspace.project().artifact}.zip`;
        a.click();
        URL.revokeObjectURL(url);
        this.toast.show(`Project downloaded as ${this.workspace.project().artifact}.zip`);
      },
      error: (err) => this.toast.show(`Download failed: ${err.error?.detail ?? err.message}`, true),
    });
  }
}

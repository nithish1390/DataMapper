import { CommonModule } from '@angular/common';
import { Component, ElementRef, ViewChild, computed, effect, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { LineMode, TreeRow, WorkspaceService } from '../../../../core/services/workspace.service';
import { FormulaCheck } from '../../../../core/models/api.models';
import { VariablesPanelComponent } from '../variables-panel/variables-panel.component';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { CustomFunctionsService } from '../custom-functions-modal/custom-functions-modal.component';
import { SessionService } from '../../../../core/services/session.service';
import { ToastService } from '../../../../core/services/toast.service';
import { StatementKind } from '../../../../core/models/api.models';

type Tab = 'functions' | 'variables' | 'constants';

interface Fn {
  name: string;
  template: string;
  desc: string;
  /** Only available when the XSLT version is 2.0. */
  v2?: boolean;
}

const FUNCTION_GROUPS: { group: string; fns: Fn[] }[] = [
  {
    group: 'Data manipulation — text', fns: [
      { name: 'concat', template: "concat(a, ' ', b)", desc: 'Joins strings: concat(FName, " ", LName)' },
      { name: 'substring', template: 'substring(s, 1, 3)', desc: 'Part of a string: 1-based start, length' },
      { name: 'substring-before', template: "substring-before(s, '-')", desc: 'Text before the first occurrence' },
      { name: 'substring-after', template: "substring-after(s, '-')", desc: 'Text after the first occurrence' },
      { name: 'string-length', template: 'string-length(s)', desc: 'Number of characters' },
      { name: 'normalize-space', template: 'normalize-space(s)', desc: 'Trims and collapses whitespace' },
      { name: 'upper-case', template: 'upper-case(s)', desc: 'UPPER CASE (XSLT 1.0: written as translate())' },
      { name: 'lower-case', template: 'lower-case(s)', desc: 'lower case (XSLT 1.0: written as translate())' },
      { name: 'translate', template: "translate(s, '-', '')", desc: 'Character-by-character replace / remove' },
      { name: 'contains', template: "contains(s, 'x')", desc: 'true if s contains x' },
      { name: 'starts-with', template: "starts-with(s, 'x')", desc: 'true if s starts with x' },
      { name: 'ends-with', template: "ends-with(s, 'x')", desc: 'true if s ends with x' },
      { name: 'string', template: 'string(x)', desc: 'Converts to text' },
      { name: 'replace', template: "replace(s, '[^0-9]', '')", desc: 'Regular-expression replace, $1 back-references', v2: true },
      { name: 'matches', template: "matches(s, '^[A-Z]{2}[0-9]{2}')", desc: 'true if s matches the regular expression', v2: true },
      { name: 'string-join', template: "string-join(Item/Nm, ', ')", desc: 'Joins all values of a repeating field', v2: true },
    ],
  },
  {
    group: 'Numbers & aggregation', fns: [
      { name: 'number', template: 'number(x)', desc: 'Converts to a number' },
      { name: 'format-number', template: "format-number(x, '#,##0.00')", desc: "Number -> text: '0.00', '#,##0.00', '000'" },
      { name: 'sum', template: 'sum(Item/Amount)', desc: 'Total of a repeating field' },
      { name: 'round', template: 'round(x)', desc: 'Nearest whole number' },
      { name: 'floor', template: 'floor(x)', desc: 'Round down' },
      { name: 'ceiling', template: 'ceiling(x)', desc: 'Round up' },
      { name: '+ - * div mod', template: 'a + b', desc: 'Arithmetic operators' },
      { name: 'abs', template: 'abs(x)', desc: 'Absolute value', v2: true },
      { name: 'min', template: 'min(Item/Amount)', desc: 'Smallest value of a repeating field', v2: true },
      { name: 'max', template: 'max(Item/Amount)', desc: 'Largest value of a repeating field', v2: true },
      { name: 'avg', template: 'avg(Item/Amount)', desc: 'Average of a repeating field', v2: true },
    ],
  },
  {
    group: 'Looping / iteration', fns: [
      { name: 'count', template: 'count(Item)', desc: 'How many elements: count(HomePhone) > 0' },
      { name: 'position', template: 'position()', desc: 'Index (1-based) of the current loop item' },
      { name: 'last', template: 'last()', desc: 'Number of items in the current loop' },
      { name: 'exists', template: 'exists(x)', desc: 'true if x is present and non-empty' },
      { name: '.  /  ..', template: '../', desc: 'Current item / parent of the current item' },
      { name: 'current-group', template: 'current-group()', desc: 'Items of the current For-Each-Group, e.g. sum(current-group()/Amt)', v2: true },
      { name: 'current-grouping-key', template: 'current-grouping-key()', desc: 'The key of the current For-Each-Group', v2: true },
    ],
  },
  {
    group: 'Conditions', fns: [
      { name: 'if', template: "if(cond, 'then', 'else')", desc: 'Inline condition (becomes xsl:choose)' },
      { name: 'when', template: "when(c1, v1, c2, v2, 'otherwise')", desc: 'Multi-branch value' },
      { name: 'and / or', template: 'a and b', desc: 'Combine conditions' },
      { name: 'not', template: 'not(x)', desc: 'Negation' },
      { name: '= != < <= > >=', template: "a = 'x'", desc: 'Comparisons' },
      { name: 'true / false', template: 'true()', desc: 'Boolean constants' },
      { name: 'boolean', template: 'boolean(x)', desc: 'Converts to true/false' },
    ],
  },
  {
    group: 'Date / time', fns: [
      { name: 'current-dateTime', template: 'current-dateTime()', desc: "Now, ISO-8601, the server's time zone (XSLT 1.0: EXSLT date:date-time)" },
      { name: 'current-dateTime(zone)', template: "current-dateTime('Asia/Singapore')",
        desc: 'Now in a time zone, e.g. 2026-10-03T14:45:15+08:00', v2: true },
      { name: 'current-date(zone)', template: "current-date('Asia/Singapore')", desc: 'Today in a time zone, e.g. 2026-10-03', v2: true },
      { name: 'format-dateTime', template: "format-dateTime(value, 'dd/MM/yyyy HH:mm:ss')",
        desc: "ISO date/dateTime -> any format. Java pattern (dd/MM/yyyy HH:mm, yyyyMMdd, dd-MMM-yy) or picture ([D01]/[M01]/[Y0001])", v2: true },
      { name: 'parse-dateTime', template: "parse-dateTime(value, 'dd/MM/yyyy HH:mm:ss')",
        desc: 'Text in a fixed-width pattern -> ISO dateTime (or date), e.g. 30/09/2026 -> 2026-09-30' },
    ],
  },
];

const CONSTANTS: { label: string; text: string }[] = [
  { label: "'' (empty string)", text: "''" },
  { label: "'text'", text: "'text'" },
  { label: 'true()', text: 'true()' },
  { label: 'false()', text: 'false()' },
  { label: '0', text: '0' },
  { label: '1', text: '1' },
  { label: 'position()', text: 'position()' },
  { label: "current-dateTime('UTC')", text: "current-dateTime('UTC')" },
];

/** Centre panel, the Mapping Builder: Functions /
 * Variables / Constants on the left (click or drag into the formula), the
 * formula with its evaluation context on the right, plus the generated XSLT
 * for the selected node. */
@Component({
  selector: 'app-formula-builder',
  standalone: true,
  imports: [CommonModule, FormsModule, VariablesPanelComponent],
  templateUrl: './formula-builder.component.html',
})
export class FormulaBuilderComponent {
  @ViewChild('formulaBox') formulaBox?: ElementRef<HTMLTextAreaElement>;

  tab = signal<Tab>('functions');
  text = signal('');
  check = signal<FormulaCheck | null>(null);
  snippet = signal('');
  hoverFn = signal<Fn | null>(null);
  /** Functions available for the selected XSLT version. */
  groups = computed(() => FUNCTION_GROUPS.map((g) => ({
    group: g.group, fns: g.fns.filter((f) => !f.v2 || this.workspace.isXslt2()),
  })).filter((g) => g.fns.length));
  hiddenFor1 = FUNCTION_GROUPS.reduce((n, g) => n + g.fns.filter((f) => f.v2).length, 0);
  /** Formula text the draft was loaded from, to tell edits apart from outside changes. */
  private loadedFormula = '';
  constants = CONSTANTS;
  private checkTimer?: ReturnType<typeof setTimeout>;
  private snippetTimer?: ReturnType<typeof setTimeout>;

  row = computed(() => this.workspace.selectedRow());

  sourceUsages = computed(() => {
    const s = this.workspace.selectedSource();
    return s ? this.workspace.usagesOf(s) : [];
  });

  /** Collapsed branch cards in the Choice view (all expanded by default). */
  collapsedBranches = signal<Set<string>>(new Set());

  /** Custom functions, one group per uploaded library (user-chosen name). */
  libraryGroups = computed(() => this.workspace.libraries().map((l) => ({
    id: l.id, name: l.name, kind: l.kind, file: l.file_name,
    fns: l.functions.map((f) => ({
      name: f.method_name, cls: f.class_name.split('.').pop() ?? '',
      template: this.jarTemplate(f.method_name, f.params),
      desc: `${f.class_name}.${f.method_name}(${f.params.join(', ')}) : ${f.ret}`,
    })),
  })));

  constructor(public workspace: WorkspaceService, private api: ApiService, private confirm: ConfirmService,
              public customFns: CustomFunctionsService, private sessions: SessionService, private toast: ToastService) {
    // Load the formula when a different row is selected. Unapplied edits of the previous row are
    // offered for applying first.
    let draftKey: string | null = null;
    effect(() => {
      const key = this.workspace.selectedRowKey();
      const r = untracked(() => this.workspace.selectedRow());
      const draft = untracked(() => this.text());
      if (draftKey && draftKey !== key && draft !== this.loadedFormula) void this.offerApply(draftKey, draft);
      draftKey = key;
      this.loadedFormula = r?.formula ?? '';
      this.text.set(this.loadedFormula);
      this.check.set(null);
      if (key) this.scheduleCheck();
      setTimeout(() => this.formulaBox?.nativeElement.focus(), 0);
    }, { allowSignalWrites: true });
    // Follow changes made elsewhere (tree cell, drag and drop) while nothing has been typed here.
    effect(() => {
      const r = this.workspace.selectedRow();
      if (!r || r.formula === this.loadedFormula) return;
      if (untracked(() => this.text()) === this.loadedFormula) {
        this.text.set(r.formula);
        this.scheduleCheck();
      }
      this.loadedFormula = r.formula;
    }, { allowSignalWrites: true });
    // The formula check depends on the XSLT version: re-check when it changes.
    effect(() => {
      this.workspace.xsltVersion();
      if (untracked(() => this.workspace.selectedRowKey())) this.scheduleCheck();
    });
    // Session saves (Ctrl/⌘+S anywhere) apply a pending draft first.
    this.sessions.beforeSave.push(() => this.applyNow());
    // Live XSLT for the selected node.
    effect(() => {
      const r = this.workspace.selectedRow();
      this.workspace.mappings();
      this.workspace.structures();
      clearTimeout(this.snippetTimer);
      if (!r || !this.workspace.target().ready) {
        this.snippet.set('');
        return;
      }
      const target = r.node.path;
      const scope = r.kind === 'element' ? r.scope : r.scopes[r.scopes.length - 1] ?? '';
      this.snippetTimer = setTimeout(() => {
        this.api.snippet(this.workspace.toWorkspace(), target, scope).subscribe({
          next: (res) => this.snippet.set(res.xslt),
          error: () => undefined,
        });
      }, 300);
    }, { allowSignalWrites: true });
  }

  // ------------------------------------------------------------ editing
  /** Problems the backend reported for the selected row (shown red under the formula). */
  rowProblems = computed(() => {
    const key = this.workspace.selectedRowKey();
    return key ? this.workspace.problems().filter((p) => p.row_key === key).map((p) => p.message) : [];
  });

  invalid = computed(() => this.check()?.ok === false || this.rowProblems().length > 0);

  /** The draft differs from what's applied on the row. */
  pending = computed(() => {
    const r = this.row();
    return !!r && this.editable(r) && this.text() !== r.formula;
  });

  kindLabel(r: TreeRow): string {
    return {
      element: r.node.children.length ? 'Element' : 'Field', 'for-each': 'For-Each — select',
      'for-each-group': 'For-Each-Group — select', if: 'If — test',
      choose: 'Choice', when: 'When — test', otherwise: 'Otherwise',
    }[r.kind];
  }

  /** Apply: writes the draft to the selected row. */
  async apply(): Promise<void> {
    const r = this.row();
    if (!r || !this.pending()) return;
    if (!this.text().trim() && r.formula.trim() && !(await this.confirm.ask(
      `Remove the ${r.kind === 'element' ? 'mapping' : 'formula'} of ${r.label}?`, 'Please confirm', 'Yes, remove'))) return;
    this.applyNow();
    this.toast.show(`Applied to ${r.label}.`);
  }

  private applyNow(): void {
    const r = this.row();
    if (!r || !this.pending()) return;
    this.workspace.setRowFormula(r, this.text());
    this.loadedFormula = this.text();
  }

  /** Save: apply, then save the session to its file. */
  async save(): Promise<void> {
    if (this.pending()) await this.apply();
    if (this.pending()) return;  // apply was cancelled
    this.sessions.saveToFile(false);
    this.toast.show(`Saved session ${this.sessions.fileName()}.`);
  }

  revert(): void {
    const r = this.row();
    this.text.set(r?.formula ?? '');
    this.scheduleCheck();
  }

  onKey(event: KeyboardEvent): void {
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key === 'Enter') {
      event.preventDefault();
      void this.apply();
    } else if (mod && event.key.toLowerCase() === 's') {
      event.preventDefault();
      event.stopPropagation();
      void this.save();
    }
  }

  private async offerApply(key: string, text: string): Promise<void> {
    const row = this.workspace.rows().find((x) => x.key === key);
    if (!row || row.formula === text) return;
    if (await this.confirm.ask(`You changed the formula of ${row.label} but didn't apply it.`,
      'Apply your changes?', 'Apply')) {
      this.workspace.setRowFormula(row, text);
      this.toast.show(`Applied to ${row.label}.`);
    }
  }

  /** Statement buttons ("Looping / iteration") surround the selected row. */
  surround(kind: StatementKind | 'copy-of'): void {
    const r = this.row();
    if (!r) return;
    const st = this.workspace.surround(r, kind);
    if (st) {
      const key = kind === 'choose' ? `w|${st.id}|${st.id}:${st.whens[0].id}` : `s|${st.id}`;
      const row = this.workspace.rows().find((x) => x.key === key);
      if (row) this.workspace.selectRow(row);
    }
  }

  setGroupBy(r: TreeRow, value: string): void {
    if (r.stmt && value !== (r.stmt.group_by ?? '')) this.workspace.updateStatementById(r.stmt.id, { group_by: value });
  }

  editable(r: TreeRow): boolean {
    return r.kind !== 'choose' && r.kind !== 'otherwise';
  }

  /** Typing edits the draft only; Apply (Ctrl/⌘+Enter) writes it to the row. */
  onInput(value: string): void {
    this.text.set(value);
    this.scheduleCheck();
  }

  insert(snippet: string): void {
    const r = this.row();
    if (!r || !this.editable(r)) return;
    const box = this.formulaBox?.nativeElement;
    const cur = this.text();
    const start = box?.selectionStart ?? cur.length;
    const end = box?.selectionEnd ?? cur.length;
    const next = cur.slice(0, start) + snippet + cur.slice(end);
    this.onInput(next);
    setTimeout(() => {
      if (!box) return;
      box.focus();
      box.selectionStart = box.selectionEnd = start + snippet.length;
    }, 0);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    const raw = event.dataTransfer?.getData('text/plain') ?? '';
    try {
      const p = JSON.parse(raw) as { sourceId?: string; path?: string; insert?: string };
      if (p.insert) return this.insert(p.insert);
      if (p.sourceId && p.sourceId !== 'target' && p.path) {
        return this.insert(this.workspace.refFor(this.row(), p.sourceId, p.path));
      }
    } catch {
      if (raw) this.insert(raw);
    }
  }

  dragText(event: DragEvent, text: string): void {
    event.dataTransfer?.setData('text/plain', JSON.stringify({ insert: text }));
  }

  /** Clears the draft (Apply then asks before removing the mapping). */
  clear(): void {
    this.onInput('');
  }

  setMode(mode: 'value' | 'copy-of'): void {
    const r = this.row();
    if (r) this.workspace.setRowMode(r, mode);
  }

  jarTemplate(name: string, params: string[]): string {
    return `${name}(${params.map((_, i) => `arg${i + 1}`).join(', ')})`;
  }

  private scheduleCheck(): void {
    clearTimeout(this.checkTimer);
    const r = this.row();
    if (!r || !this.editable(r)) return;
    this.checkTimer = setTimeout(() => {
      const text = this.text();
      if (!text.trim()) {
        this.check.set(null);
        return;
      }
      this.api.checkFormula(this.workspace.toWorkspace(), text, r.node.path, r.kind === 'for-each' || r.kind === 'for-each-group').subscribe({
        next: (c) => this.check.set(c),
        error: () => undefined,
      });
    }, 300);
  }

  // ------------------------------------------------------------- choose
  whenRows(r: TreeRow): TreeRow[] {
    return this.workspace.rows().filter((x) => x.stmt?.id === r.stmt?.id && (x.kind === 'when' || x.kind === 'otherwise'));
  }

  /** The Choice row that owns a [When]/[Otherwise] row (or the row itself). */
  chooseRowOf(r: TreeRow): TreeRow | null {
    if (r.kind === 'choose') return r;
    return this.workspace.rows().find((x) => x.kind === 'choose' && x.stmt?.id === r.stmt?.id) ?? null;
  }

  /** Everything mapped inside one branch: fields with formulas and nested statements. */
  branchItems(branch: TreeRow): { row: TreeRow; rel: string }[] {
    const base = branch.node.path;
    return this.workspace.rows()
      .filter((x) => x.scopes.includes(branch.branchKey) &&
        ((x.kind === 'element' && !!x.mapping && !x.inherited) || x.kind === 'for-each' || x.kind === 'for-each-group' || x.kind === 'if' ||
         x.kind === 'when' || x.kind === 'choose'))
      .map((x) => ({ row: x, rel: x.node.path === base ? x.label : x.node.path.slice(base.length + 1) + (x.kind !== 'element' ? ` ${x.label.replace(/^.* - /, '')}` : '') }));
  }

  isBranchOpen(b: TreeRow): boolean {
    return !this.collapsedBranches().has(b.key);
  }

  toggleBranch(b: TreeRow): void {
    const next = new Set(this.collapsedBranches());
    next.has(b.key) ? next.delete(b.key) : next.add(b.key);
    this.collapsedBranches.set(next);
  }

  setBranchTest(b: TreeRow, value: string): void {
    if (value !== b.formula) this.workspace.setRowFormula(b, value);
  }

  async deleteBranch(b: TreeRow): Promise<void> {
    const n = this.branchItems(b).length;
    const what = b.kind === 'when' ? 'this [When] branch' : 'the [Otherwise] branch';
    if (await this.confirm.ask(`Delete ${what}${n ? ` and its ${n} mapping(s)` : ''}?`)) this.workspace.clearRow(b);
  }

  async deleteChoice(r: TreeRow): Promise<void> {
    if (r.stmt && await this.confirm.ask(
      `Delete the Choice on ${r.node.name}? The first [When] branch's mappings are kept; the other branches are deleted.`)) {
      this.workspace.removeStatementById(r.stmt.id);
    }
  }

  async deleteStatement(r: TreeRow): Promise<void> {
    if (r.stmt && await this.confirm.ask(`Remove the ${r.stmt.kind} statement on ${r.node.name}?`)) {
      this.workspace.removeStatementById(r.stmt.id);
    }
  }

  // ------------------------------------------------------------- misc
  setLineMode(mode: LineMode): void {
    this.workspace.lineMode.set(mode);
  }

  openRowKey(key: string): void {
    const row = this.workspace.rows().find((x) => x.key === key);
    if (row) this.workspace.selectRow(row);
  }

  /** Mappings list for the empty state. */
  allMappings = computed(() =>
    this.workspace.mappings().map((m) => ({ key: `e|${m.target}|${m.scope ?? ''}`, target: m.target, scope: m.scope ?? '',
      formula: m.transform || (m.inputs[0] ? `$${m.inputs[0].source_id}/…` : '') })));
}

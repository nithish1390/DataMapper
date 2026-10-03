import { CommonModule } from '@angular/common';
import { Component, computed } from '@angular/core';
import { StatementKind } from '../../../../core/models/api.models';
import { TreeRow, WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { ContextMenuService, MenuItem } from '../../../../shared/components/context-menu/context-menu.component';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';

const ICON: Record<string, string> = {
  'for-each': '⟳', 'for-each-group': '⧉⟳', if: '?', choose: '⋯', when: '?=', otherwise: '*=',
  'var-header': '$', variable: '$', 'local-variable': '$',
};

/** The target side of the mapper, with statements
 * ([For-Each], [Choose] › [When]/[Otherwise], [If]) are rows of the tree, each
 * row has an inline XPath formula, and right-click opens the statement menu. */
@Component({
  selector: 'app-target-mapper',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './target-mapper.component.html',
})
export class TargetMapperComponent {
  private clipboard = '';

  /** Red rows: backend problems (bad formula, missing source path, empty for-each/When…),
   * mandatory fields/elements with nothing mapped where their parent is written, and
   * choices with no option mapped. Ancestors of a red row get a red marker too. */
  issues = computed(() => {
    const rows = this.workspace.rows();
    const msgs = new Map<string, string[]>();
    const add = (key: string, msg: string) => msgs.set(key, [...(msgs.get(key) ?? []), msg]);
    this.workspace.problems().forEach((p) => add(p.row_key, p.message));
    const anyMapped = this.workspace.mappings().length > 0 || this.workspace.structures().length > 0;
    // Paths that receive content — explicitly or through a parent's Copy-Of.
    const filled = new Set(rows.filter((r) => r.kind === 'element' && r.hasContent).map((r) => r.node.path));
    const stack: { depth: number; written: boolean }[] = [];
    for (const r of rows) {
      while (stack.length && stack[stack.length - 1].depth >= r.depth) stack.pop();
      const parentWritten = stack.length ? stack[stack.length - 1].written : anyMapped;
      let written = parentWritten;
      if (r.kind === 'element') {
        const mandatory = !r.excluded && this.isMandatory(r);
        written = !r.excluded && (r.hasContent || (mandatory && parentWritten));
        if (mandatory && parentWritten && !r.hasContent) {
          add(r.key, r.node.children.length ? 'Mandatory element: nothing is mapped inside it' : 'Mandatory field is not mapped');
        }
        if (written && r.node.children.length) {
          const groups = [...new Set(r.node.children.map((c) => c.choice).filter((g): g is string => !!g))];
          for (const g of groups) {
            const alts = r.node.children.filter((c) => c.choice === g);
            const sel = this.workspace.target().choice_selections?.[g];
            const mapped = alts.some((c) => filled.has(c.path));
            if (!mapped && !sel) add(r.key, `Choice: select and map one of ${alts.map((a) => a.name.replace('[]', '')).join(' | ')}`);
          }
        }
      }
      stack.push({ depth: r.depth, written });
    }
    const ancestors = new Set<string>();
    rows.forEach((r, i) => {
      if (!msgs.has(r.key)) return;
      let d = r.depth;
      for (let j = i - 1; j >= 0 && d > 0; j--) {
        if (rows[j].depth < d) {
          ancestors.add(rows[j].key);
          d = rows[j].depth;
        }
      }
    });
    return { msgs, ancestors };
  });

  issueText(r: TreeRow): string {
    const m = this.issues().msgs.get(r.key);
    if (m) return '⚠ ' + m.join('\n⚠ ');
    if (this.issues().ancestors.has(r.key)) return 'Something below has a mapping issue';
    return r.node.path;
  }

  constructor(
    public workspace: WorkspaceService,
    private toast: ToastService,
    private menu: ContextMenuService,
    private confirm: ConfirmService,
  ) {}

  trackRow = (_: number, r: TreeRow) => r.key;

  // ------------------------------------------------------------- display
  icon(r: TreeRow): string {
    if (r.kind !== 'element') return ICON[r.kind];
    if (r.node.name.startsWith('@')) return '@';
    if (r.node.type === 'object' || r.node.type === 'array') return '▤';
    return { integer: '123', number: '1.2', boolean: 'T/F' }[r.node.type as string] ?? 'ABC';
  }

  isMandatory(r: TreeRow): boolean {
    return this.workspace.isMandatory(r.node.path, r.node.mandatory);
  }

  /** Repeating marks: * repeating, + repeating & required. */
  marker(r: TreeRow): string {
    if (r.kind !== 'element' || r.node.type !== 'array') return '';
    return this.isMandatory(r) ? '+' : '*';
  }

  // ------------------------------------------------------------- choice
  choiceSelected(r: TreeRow): boolean {
    return !!r.choiceGroup && this.workspace.target().choice_selections?.[r.choiceGroup] === r.node.path;
  }

  choiceTitle(r: TreeRow): string {
    const alts = this.workspace.choiceAlternatives(r.choiceGroup!).map((a) => a.name.replace('[]', ''));
    return `Choice — only one of ${alts.join(' | ')} is written. Click to ${this.choiceSelected(r) ? 'clear the selection' : 'use ' + r.label}.`;
  }

  async pickChoice(r: TreeRow, event?: Event): Promise<void> {
    event?.stopPropagation();
    if (!r.choiceGroup) return;
    if (this.choiceSelected(r)) {
      this.workspace.selectChoice(r.choiceGroup, null);
      return;
    }
    const others = this.workspace.choiceAlternatives(r.choiceGroup).filter((a) => a.path !== r.node.path)
      .filter((a) => this.workspace.mappings().some((m) => m.target === a.path || m.target.startsWith(`${a.path}.`)));
    if (others.length && !(await this.confirm.ask(
      `${others.map((o) => o.name).join(', ')} already has mappings. They will be kept but not written while ${r.label} is selected.`,
      `Use ${r.label}?`, 'Yes, use it'))) return;
    this.workspace.selectChoice(r.choiceGroup, r.node.path);
  }

  label(r: TreeRow): string {
    if (r.kind === 'element' && r.isCopy) return `${r.label} - [Copy-Of]`;
    return r.label;
  }

  placeholder(r: TreeRow): string {
    switch (r.kind) {
      case 'for-each':
      case 'for-each-group': return 'repeating source, e.g. $s1/Doc/Item';
      case 'if':
      case 'when': return "test, e.g. count(Phone) > 0";
      case 'variable':
      case 'local-variable': return "value, e.g. count(Item)  or  $s1/Doc/Field";
      case 'choose': return '';
      case 'otherwise': return '';
      default: return r.node.children.length ? '' : '';
    }
  }

  editable(r: TreeRow): boolean {
    return r.kind !== 'choose' && r.kind !== 'otherwise' && r.kind !== 'var-header';
  }

  /** Data type shown next to a variable's name. */
  varType(r: TreeRow): string {
    return (r.kind === 'variable' ? r.variable?.var_type : r.stmt?.var_type) ?? 'string';
  }

  addGlobalVariable(): void {
    const v = this.workspace.addVariable();
    if (this.workspace.targetCollapsed().has('vh')) this.workspace.toggleRow('vh');
    const row = this.workspace.rows().find((x) => x.key === `v|${v.id}`);
    if (row) this.workspace.selectRow(row);
  }

  addLocalVariable(r: TreeRow | null): void {
    if (!r || r.kind !== 'element') return this.toast.show('Select a target element first — the variable is declared right before it.', true);
    const st = this.workspace.addLocalVariable(r);
    const row = this.workspace.rows().find((x) => x.key === `s|${st.id}`);
    if (row) this.workspace.selectRow(row);
  }

  // ------------------------------------------------------------- actions
  select(r: TreeRow): void {
    this.workspace.selectRow(r);
  }

  toggle(r: TreeRow, event: Event): void {
    event.stopPropagation();
    this.workspace.toggleRow(r.key);
  }

  commit(r: TreeRow, event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (value !== r.formula) this.workspace.setRowFormula(r, value);
  }

  allowDrop(event: DragEvent): void {
    event.preventDefault();
  }

  drop(r: TreeRow, event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    const raw = event.dataTransfer?.getData('text/plain');
    if (!raw) return;
    try {
      const p = JSON.parse(raw) as { sourceId?: string; path?: string };
      if (!p.sourceId || p.sourceId === 'target' || !p.path) return;
      const msg = this.workspace.dropOnRow(r, p.sourceId, p.path);
      if (msg) this.toast.show(msg);
      this.workspace.selectRow(this.workspace.rows().find((x) => x.key === r.key) ?? r);
    } catch {
      /* not a field drag */
    }
  }

  surround(r: TreeRow | null, kind: StatementKind | 'copy-of'): void {
    if (!r) return this.toast.show('Select a target row first.', true);
    const st = this.workspace.surround(r, kind);
    if (!st) return;
    // Select the new statement row so its formula can be typed straight away.
    const key = kind === 'choose' ? `w|${st.id}|${st.id}:${st.whens[0].id}` : `s|${st.id}`;
    const row = this.workspace.rows().find((x) => x.key === key);
    if (row) this.workspace.selectRow(row);
  }

  move(r: TreeRow | null, delta: -1 | 1): void {
    if (r?.stmt && (r.kind === 'for-each' || r.kind === 'for-each-group' || r.kind === 'if' || r.kind === 'choose')) {
      this.workspace.moveStatementById(r.stmt.id, delta);
    } else {
      this.toast.show('Select a [For-Each], [If] or [Choose] row to move it.', true);
    }
  }

  /** Right-click "Clear mapping": the row and everything below it (the whole mapping at the root). */
  clearLabel(r: TreeRow): string {
    if (r.kind === 'var-header') return 'Clear all variables';
    if (this.workspace.isRootRow(r)) return 'Clear all mappings';
    if (r.kind === 'when' || r.kind === 'otherwise') return 'Clear mappings in this branch';
    return r.expandable || r.stmt ? 'Clear mapping (this and all below)' : 'Clear mapping';
  }

  async clearBelow(r: TreeRow | null): Promise<void> {
    if (!r) return;
    const p = this.workspace.clearPreview(r);
    if (!p.mappings && !p.stmts && !p.vars) return this.toast.show('Nothing mapped here.');
    const parts = [
      p.mappings ? `${p.mappings} mapping${p.mappings > 1 ? 's' : ''}` : '',
      p.stmts ? `${p.stmts} statement${p.stmts > 1 ? 's' : ''} (For-Each, Choice, If, local variables …)` : '',
      p.vars ? `${p.vars} global variable${p.vars > 1 ? 's' : ''}` : '',
    ].filter(Boolean).join(', ');
    const name = r.node.name;
    const where = r.kind === 'var-header' ? 'the Variables section'
      : this.workspace.isRootRow(r) ? `the whole mapping (root ${name})`
      : r.kind === 'when' || r.kind === 'otherwise' ? `this ${r.label} branch of ${name} (the branch itself is kept)`
      : `${name} and all its child fields`;
    if (await this.confirm.ask(`This removes ${parts} from ${where}. Target fields themselves are not deleted.`,
      this.clearLabel(r) + '?', 'Yes, clear')) {
      this.workspace.clearBelow(r);
      this.toast.show('Mapping cleared.');
    }
  }

  async clear(r: TreeRow | null): Promise<void> {
    if (!r) return;
    if (r.kind === 'element' || r.kind === 'var-header') return this.clearBelow(r);
    const what = r.kind === 'variable' ? `the variable ${r.label}` : r.kind === 'local-variable' ? `the variable ${r.label.replace(' - [Variable]', '')}` :
      r.kind === 'when' ? 'this [When] branch and its mappings' :
      r.kind === 'otherwise' ? 'the [Otherwise] branch and its mappings' :
      r.kind === 'choose' ? `the Choice on ${r.node.name} (the first [When] branch's mappings are kept)` : `the ${r.label} statement`;
    if (await this.confirm.ask(`Delete ${what}?`)) this.workspace.clearRow(r);
  }

  private async removeStatement(r: TreeRow): Promise<void> {
    if (r.stmt && await this.confirm.ask(`Remove the ${r.stmt.kind} statement on ${r.node.name}?`)) {
      this.workspace.removeStatementById(r.stmt.id);
    }
  }

  addWhen(r: TreeRow | null): void {
    if (r?.stmt?.kind === 'choose') this.workspace.addWhen(r.stmt.id);
    else this.toast.show('Select a [Choose] or [When] row.', true);
  }

  // --------------------------------------------------------- right-click
  openMenu(r: TreeRow, event: MouseEvent): void {
    this.workspace.selectRow(r);
    const isEl = r.kind === 'element';
    const isStmt = !isEl;
    const choose = r.stmt?.kind === 'choose';
    const items: MenuItem[] = [
      { label: 'Edit', hint: 'Mapping Builder', action: () => this.workspace.selectRow(r) },
      { label: 'Add variable here (before this element)', disabled: !isEl, action: () => this.addLocalVariable(r) },
      { label: 'Add global variable', action: () => this.addGlobalVariable() },
      ...(r.choiceGroup && isEl ? [{ label: this.choiceSelected(r) ? 'Clear choice selection' : `Use this choice option (${r.label})`,
        action: () => this.pickChoice(r) } as MenuItem] : []),
      {
        label: 'Expand', children: [
          { label: 'Expand all below', action: () => this.workspace.setSubtreeCollapsed(r, false) },
          { label: 'Collapse all below', action: () => this.workspace.setSubtreeCollapsed(r, true) },
        ],
      },
      {
        label: 'Show Connected', action: () => {
          this.workspace.lineMode.set('selected');
          this.workspace.selectRow(r);
        },
      },
      { separator: true },
      {
        label: 'Statement', children: [
          { label: 'Surround with Choice…', action: () => this.surround(r, 'choose') },
          { label: 'Surround with If…', action: () => this.surround(r, 'if') },
          { label: 'Surround with For-Each…', action: () => this.surround(r, 'for-each') },
          ...(this.workspace.isXslt2() ? [{ label: 'Surround with For-Each-Group… (XSLT 2.0)',
            action: () => this.surround(r, 'for-each-group') } as MenuItem] : []),
          { label: isEl && r.mapping?.mode === 'copy-of' ? 'Use Value-Of' : 'Copy-Of (copy source element)',
            disabled: !isEl,
            action: () => (r.mapping?.mode === 'copy-of' ? this.workspace.setRowMode(r, 'value') : this.surround(r, 'copy-of')) },
          { separator: true },
          { label: 'Add [When]', disabled: !choose, action: () => this.workspace.addWhen(r.stmt!.id) },
          { label: r.stmt?.otherwise !== null && choose ? 'Remove [Otherwise]' : 'Add [Otherwise]', disabled: !choose,
            action: () => this.workspace.setOtherwise(r.stmt!.id, r.stmt!.otherwise === null) },
          { separator: true },
          { label: 'Move statement up (outward)', disabled: !isStmt || r.kind === 'when' || r.kind === 'otherwise',
            action: () => this.move(r, -1) },
          { label: 'Move statement down (inward)', disabled: !isStmt || r.kind === 'when' || r.kind === 'otherwise',
            action: () => this.move(r, 1) },
          { label: 'Remove statement', disabled: !isStmt, action: () => this.removeStatement(r) },
        ],
      },
      { separator: true },
      { label: 'Copy formula', disabled: !r.formula, action: () => this.copyFormula(r) },
      { label: 'Paste formula', disabled: !this.clipboard || !this.editable(r),
        action: () => this.workspace.setRowFormula(r, this.clipboard) },
      { separator: true },
      ...(r.kind === 'variable' || r.kind === 'local-variable' ? [] : [{ label: this.clearLabel(r), disabled: !this.hasClearable(r),
        action: () => this.clearBelow(r) } as MenuItem]),
      ...(isStmt && r.kind !== 'var-header' ? [{ label: r.kind === 'variable' || r.kind === 'local-variable' ? 'Delete variable'
        : r.kind === 'when' ? 'Delete [When]' : r.kind === 'otherwise' ? 'Delete [Otherwise]' : 'Delete statement',
        action: () => this.clear(r) } as MenuItem] : []),
    ];
    if (isEl) {
      items.push({ separator: true }, {
        label: 'Field', children: [
          { label: this.isMandatory(r) ? 'Mark optional' : 'Mark mandatory',
            action: () => this.workspace.toggleMandatory(r.node.path, r.node.mandatory) },
          { label: 'Add child field', disabled: !r.node.children.length, action: () => this.addChild(r) },
          { label: 'Rename…', action: () => this.rename(r) },
        ],
      });
    }
    this.menu.open(event, items);
  }

  private hasClearable(r: TreeRow): boolean {
    const p = this.workspace.clearPreview(r);
    return !!(p.mappings || p.stmts || p.vars);
  }

  private copyFormula(r: TreeRow): void {
    this.clipboard = r.formula;
    navigator.clipboard?.writeText(r.formula).catch(() => undefined);
    this.toast.show('Formula copied.');
  }

  private addChild(r: TreeRow): void {
    const path = this.workspace.addTargetField(r.node.path);
    if (path) this.renamePath(path);
  }

  private rename(r: TreeRow): void {
    this.renamePath(r.node.path);
  }

  private renamePath(path: string): void {
    const current = path.split('.').pop()!.replace(/\[\]$/, '');
    const name = window.prompt('Field name:', current);
    if (!name || name === current) return;
    if (!this.workspace.renameTargetField(path, name)) {
      this.toast.show('Field name must be a valid identifier (letters, numbers, underscore).', true);
    }
  }
}

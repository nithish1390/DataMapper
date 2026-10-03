import { Injectable, computed, effect, signal, untracked } from '@angular/core';
import {
  FieldNode, FunctionLibrary, JarFunction, LlmProviderConfig, MappingLink, RowProblem, MappingRule, MappingWorkspace,
  ProjectSettings, RootCondition, SourceFormat, SourceRef, SourceSpec, Statement, StatementKind,
  TargetSpec, TargetStructure, VariableRule,
} from '../models/api.models';
import {
  LoopRef, branchKey, copyPairs, displayMappingFormula, hasElementChildren, displaySelect, displayTest, newId, normalizeStatement,
  otherwiseKey, refText, resolvePath, treeSegs,
} from './formula';

export type LineMode = 'all' | 'selected' | 'none';

/** A saved session file (Sessions › Save): the complete editable state of the mapper. */
export interface SessionFile {
  format: 'mapsheet-ai-session' | 'datamapper-session';
  version: 1;
  name: string;
  saved_at: string;
  state: {
    sources: (Omit<UiSource, 'collapsed'> & { collapsed: string[] })[];
    target: Omit<UiTarget, 'collapsed'> & { collapsed: string[] };
    mappings: MappingRule[];
    variables: VariableRule[];
    root_condition: RootCondition;
    structures: TargetStructure[];
    project: ProjectSettings;
    llm: LlmProviderConfig;
    libraries: FunctionLibrary[];
    sample_inputs: Record<string, string>;
    target_collapsed: string[];
    line_mode: LineMode;
  };
}

export interface UiSource extends SourceSpec {
  ready: boolean;
  raw: string;
  collapsed: Set<string>;
  panelCollapsed: boolean;
}

export interface UiTarget extends TargetSpec {
  ready: boolean;
  raw: string;
  collapsed: Set<string>;
}

export type RowKind = 'element' | 'for-each' | 'for-each-group' | 'if' | 'choose' | 'when' | 'otherwise';

/** One row of the target mapping tree: an element, or a statement around it. */
export interface TreeRow {
  /** Matches the backend's link row_key: e|path|scope, s|stmtId, w|stmtId|branchKey, o|stmtId */
  key: string;
  kind: RowKind;
  node: FieldNode;
  depth: number;
  /** Active choose-branch chain; the innermost one is `scope`. */
  scopes: string[];
  scope: string;
  /** for-each context the row's formula is evaluated in. */
  ctx: LoopRef[];
  label: string;
  formula: string;
  /** Element rows: the mapping shown comes from an outer scope. */
  inherited: boolean;
  mapping: MappingRule | null;
  stmt: Statement | null;
  branchIndex: number;
  branchKey: string;
  expandable: boolean;
  collapsed: boolean;
  hidden: boolean;
  /** Something is mapped here or below. */
  hasContent: boolean;
  /** xs:choice group this element is an alternative of. */
  choiceGroup: string | null;
  /** An alternative of a choice where the user picked a different one. */
  excluded: boolean;
  /** Value comes from an ancestor's Copy-Of (display only — map it to override). */
  implied: boolean;
  /** Copy-Of matched this field to a differently named source field (e.g. BIC -> BICFI). */
  fuzzy?: boolean;
  /** Element rows: this mapping copies a whole source element (explicit Copy-Of, or a plain
   * path mapped onto an element that has children). */
  isCopy: boolean;
}

let sourceSeq = 0;
let varIdSeq = 0;

const sameRef = (a: SourceRef, b: SourceRef) => a.source_id === b.source_id && a.path === b.path;
const leafName = (n: FieldNode) => n.name.replace(/\[\]$/, '').toLowerCase();
const tagOf = (n: FieldNode) => n.name.replace(/\[\]$/, '');
const inSubtree = (p: string, root: string) => p === root || p.startsWith(`${root}.`);

function newSource(label?: string): UiSource {
  sourceSeq++;
  return {
    id: `s${sourceSeq}`, label: label ?? `Source ${sourceSeq}`, type: 'jsonschema',
    fields: [], ready: false, raw: '', collapsed: new Set(), panelCollapsed: false,
  };
}

/** All mutable app state lives here as signals. Components read via the
 * exposed signals/computed values and call the mutator methods below —
 * nothing mutates `sources`/`target`/`mappings` directly from a component. */
@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  readonly sources = signal<UiSource[]>([newSource()]);
  readonly target = signal<UiTarget>({
    type: 'jsonschema', fields: [], mandatory_overrides: {}, ready: false, raw: '', collapsed: new Set(),
  });
  readonly mappings = signal<MappingRule[]>([]);
  readonly variables = signal<VariableRule[]>([]);
  readonly rootCondition = signal<RootCondition>({ inputs: [], transform: '' });
  readonly structures = signal<TargetStructure[]>([]);
  readonly project = signal<ProjectSettings>({
    group: 'com.example', artifact: 'schema-mapper', package: 'com.example.schemamapper',
    java_version: '21', boot_version: '3.3.4', dep_web: true, dep_lombok: true, dep_camel: false, dep_jackson: true,
    xslt_version: '2.0',
  });
  readonly llm = signal<LlmProviderConfig>({ provider: 'openai', custom_headers: [] });
  /** Uploaded custom-function libraries (.jar / .java), each a named group. */
  readonly libraries = signal<FunctionLibrary[]>([]);
  readonly jarFunctions = computed<JarFunction[]>(() =>
    this.libraries().flatMap((l) => l.functions.map((f) => ({ ...f, group: l.name }))));

  /** UI-only state (not sent to the backend). */
  readonly selectedSource = signal<SourceRef | null>(null);
  readonly detailTarget = signal<string | null>(null); // a target path, or '__ROOT__'
  readonly selectedRowKey = signal<string | null>(null);
  readonly targetCollapsed = signal<Set<string>>(new Set());
  readonly lineMode = signal<LineMode>('all');
  /** Resolved source -> target links (from the backend), for lines and "used" markers. */
  readonly links = signal<MappingLink[]>([]);
  /** Per-row mapping problems from the backend (bad formula, missing source path, …). */
  readonly problems = signal<RowProblem[]>([]);
  /** Bump to force the background check (links + red markers) to run again. */
  readonly analysisTick = signal(0);

  requestAnalysis(): void {
    this.analysisTick.update((n) => n + 1);
  }

  /** Bumped whenever tree layout changes, so mapping lines redraw. */
  readonly layoutTick = signal(0);

  readonly anySourceReady = computed(() => this.sources().some((s) => s.ready));
  readonly xsltVersion = computed(() => this.project().xslt_version ?? '2.0');
  readonly isXslt2 = computed(() => this.xsltVersion() === '2.0');

  setXsltVersion(v: '1.0' | '2.0'): void {
    this.project.set({ ...this.project(), xslt_version: v });
  }
  /** Anything worth warning about before the page is closed or refreshed. */
  /** Session name (Sessions › name); used as the saved file name. */
  readonly sessionName = signal('Untitled session');
  /** Bumped on every change to the mapping state; compared with savedTick for "unsaved changes". */
  private readonly changeTick = signal(0);
  private readonly savedTick = signal(0);
  readonly unsaved = computed(() => this.dirty() && this.changeTick() !== this.savedTick());

  constructor() {
    let first = true;
    try {
      this.trackChanges(() => first, () => (first = false));
    } catch {
      /* created outside Angular (unit scripts): no change tracking */
    }
  }

  private trackChanges(isFirst: () => boolean, done: () => void): void {
    effect(() => {
      this.sources(); this.target(); this.mappings(); this.structures(); this.variables();
      this.rootCondition(); this.libraries(); this.project(); this.llm(); this.sessionName();
      const next = untracked(() => this.changeTick()) + 1;
      this.changeTick.set(next);
      if (isFirst()) {
        done();
        this.savedTick.set(next);  // a fresh app has nothing unsaved
      }
    }, { allowSignalWrites: true });
  }

  markSaved(): void {
    this.savedTick.set(this.changeTick());
  }

  readonly dirty = computed(() =>
    this.anySourceReady() || this.target().ready || this.mappings().length > 0 || this.libraries().length > 0);
  readonly sourceIds = computed(() => this.sources().map((s) => s.id));

  /** Every row of the target tree (hidden ones flagged), statements shown as rows. */
  readonly rows = computed<TreeRow[]>(() => this.buildRows());
  readonly visibleRows = computed(() => this.rows().filter((r) => !r.hidden));
  readonly selectedRow = computed(() => {
    const key = this.selectedRowKey();
    return key ? this.rows().find((r) => r.key === key) ?? null : null;
  });

  // ------------------------------------------------------------ sources
  addSource(): void {
    this.sources.update((list) => [...list, newSource()]);
  }

  removeSource(id: string): void {
    if (this.sources().length <= 1) return;
    this.sources.update((list) => list.filter((s) => s.id !== id));
    this.mappings.update((list) =>
      list
        .map((m) => ({ ...m, inputs: m.inputs.filter((i) => i.source_id !== id) }))
        .filter((m) => m.inputs.length > 0 || m.transform.trim()),
    );
    this.variables.update((list) =>
      list.map((v) => ({ ...v, inputs: v.inputs.filter((i) => i.source_id !== id) })),
    );
    this.structures.update((list) =>
      list.map((st) => ({ ...st, statements: st.statements.map((s) => ({ ...s, inputs: s.inputs.filter((i) => i.source_id !== id) })) })),
    );
  }

  patchSource(id: string, patch: Partial<UiSource>): void {
    this.sources.update((list) => list.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  setSourceParsed(id: string, tree: FieldNode[], namespace?: string | null): void {
    this.patchSource(id, { fields: tree, ready: true, collapsed: new Set(), namespace: namespace ?? null });
  }

  findSourceNode(sourceId: string, path: string): FieldNode | null {
    const s = this.sources().find((x) => x.id === sourceId);
    return s ? this.findNode(s.fields, path) : null;
  }

  findTargetNode(path: string): FieldNode | null {
    return this.findNode(this.target().fields, path);
  }

  /** The source node a for-each context points at (for the Mapping Builder's "(current item)"). */
  sourceNodeAt(loop: LoopRef): FieldNode | null {
    const s = this.sources().find((x) => x.id === loop.sid);
    if (!s) return null;
    let nodes = s.fields;
    let found: FieldNode | null = null;
    for (const seg of loop.segs) {
      found = nodes.find((n) => tagOf(n) === seg) ?? null;
      if (!found) return null;
      nodes = found.children;
    }
    return found;
  }

  // ------------------------------------------------------------- target
  patchTarget(patch: Partial<UiTarget>): void {
    this.target.update((t) => ({ ...t, ...patch }));
  }

  setTargetParsed(tree: FieldNode[], namespace?: string | null): void {
    this.patchTarget({ fields: tree, ready: true, collapsed: new Set(), namespace: namespace ?? null });
    // Start with deep containers collapsed (big XSDs).
    const collapsed = new Set<string>();
    const walk = (nodes: FieldNode[], depth: number) =>
      nodes.forEach((n) => {
        if (hasElementChildren(n) && depth >= 2) collapsed.add(`e|${n.path}|`);
        walk(n.children, depth + 1);
      });
    walk(tree, 0);
    this.targetCollapsed.set(collapsed);
  }

  setTargetType(type: SourceFormat): void {
    this.patchTarget({ type });
  }

  toggleMandatory(path: string, autoValue: boolean): void {
    const current = this.isMandatory(path, autoValue);
    this.patchTarget({ mandatory_overrides: { ...this.target().mandatory_overrides, [path]: !current } });
  }

  isMandatory(path: string, autoValue: boolean): boolean {
    const overrides = this.target().mandatory_overrides;
    return path in overrides ? overrides[path] : autoValue;
  }

  // --------------------------------------------------------- tree editing
  private findNode(nodes: FieldNode[], path: string): FieldNode | null {
    for (const n of nodes) {
      if (n.path === path) return n;
      const found = this.findNode(n.children, path);
      if (found) return found;
    }
    return null;
  }

  private findChildrenArray(nodes: FieldNode[], path: string): FieldNode[] | null {
    for (const n of nodes) {
      if (n.path === path) return n.children;
      const found = this.findChildrenArray(n.children, path);
      if (found) return found;
    }
    return null;
  }

  addTargetField(parentPath: string): string {
    const tree = structuredClone(this.target().fields);
    const arr = parentPath ? this.findChildrenArray(tree, parentPath) : tree;
    if (!arr) return '';
    let name = 'newField';
    let n = 1;
    while (arr.some((c) => c.name.replace(/\[\]$/, '') === name)) {
      n += 1;
      name = `newField${n}`;
    }
    const path = parentPath ? `${parentPath}.${name}` : name;
    arr.push({ name, path, type: 'string', mandatory: false, children: [] });
    this.patchTarget({ fields: tree });
    return path;
  }

  renameTargetField(oldPath: string, newLeafName: string): boolean {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(newLeafName)) return false;
    const tree = structuredClone(this.target().fields);
    const node = this.findNode(tree, oldPath);
    if (!node) return false;
    const lastSeg = oldPath.split('.').pop()!;
    const hasArraySuffix = lastSeg.endsWith('[]');
    const newLastSeg = newLeafName + (hasArraySuffix ? '[]' : '');
    const prefixPath = oldPath.slice(0, oldPath.length - lastSeg.length);
    const newPath = prefixPath + newLastSeg;
    const renamePrefix = (p: string) =>
      p === oldPath ? newPath : p.startsWith(`${oldPath}.`) ? newPath + p.slice(oldPath.length) : p;
    const walk = (n: FieldNode) => {
      n.path = renamePrefix(n.path);
      if (n.path === newPath) n.name = newLastSeg;
      n.children.forEach(walk);
    };
    walk(node);
    this.mappings.update((list) => list.map((m) => ({ ...m, target: renamePrefix(m.target) })));
    this.structures.update((list) => list.map((st) => ({ ...st, target: renamePrefix(st.target) })));
    if (this.detailTarget()) this.detailTarget.set(renamePrefix(this.detailTarget()!));
    this.selectedRowKey.set(null);
    const overrides: Record<string, boolean> = {};
    Object.entries(this.target().mandatory_overrides).forEach(([k, v]) => (overrides[renamePrefix(k)] = v));
    this.patchTarget({ fields: tree, mandatory_overrides: overrides });
    return true;
  }

  deleteTargetField(path: string): void {
    const tree = structuredClone(this.target().fields);
    const removeFrom = (nodes: FieldNode[]): boolean => {
      const idx = nodes.findIndex((n) => n.path === path);
      if (idx >= 0) {
        nodes.splice(idx, 1);
        return true;
      }
      return nodes.some((n) => removeFrom(n.children));
    };
    removeFrom(tree);
    this.mappings.update((list) => list.filter((m) => !inSubtree(m.target, path)));
    this.structures.update((list) => list.filter((st) => !inSubtree(st.target, path)));
    if (this.detailTarget() === path) this.detailTarget.set(null);
    this.selectedRowKey.set(null);
    this.patchTarget({ fields: tree });
  }

  toggleCollapse(side: 'target' | string, path: string): void {
    if (side === 'target') {
      this.toggleRow(path);
      return;
    }
    const s = this.sources().find((x) => x.id === side);
    if (!s) return;
    const next = new Set(s.collapsed);
    next.has(path) ? next.delete(path) : next.add(path);
    this.patchSource(side, { collapsed: next });
    this.bumpLayout();
  }

  toggleRow(key: string): void {
    const next = new Set(this.targetCollapsed());
    next.has(key) ? next.delete(key) : next.add(key);
    this.targetCollapsed.set(next);
    this.bumpLayout();
  }

  /** Expand (or collapse) a row and everything under it. */
  setSubtreeCollapsed(row: TreeRow, collapsed: boolean): void {
    const rows = this.rows();
    const start = rows.indexOf(row);
    const next = new Set(this.targetCollapsed());
    for (let i = start; i < rows.length; i++) {
      if (i > start && rows[i].depth <= row.depth) break;
      if (rows[i].expandable) collapsed ? next.add(rows[i].key) : next.delete(rows[i].key);
    }
    this.targetCollapsed.set(next);
    this.bumpLayout();
  }

  setAllCollapsed(collapsed: boolean): void {
    this.targetCollapsed.set(collapsed ? new Set(this.rows().filter((r) => r.expandable && r.depth > 0).map((r) => r.key)) : new Set());
    this.bumpLayout();
  }

  bumpLayout(): void {
    this.layoutTick.update((n) => n + 1);
  }

  selectRow(row: TreeRow | null): void {
    this.selectedRowKey.set(row?.key ?? null);
    this.detailTarget.set(row?.node.path ?? null);
  }

  // ------------------------------------------------------------- lookups
  mappingAt(path: string, scopes: string[]): MappingRule | null {
    const list = this.mappings();
    for (const sc of [...scopes].reverse().concat([''])) {
      const m = list.find((x) => x.target === path && (x.scope ?? '') === sc);
      if (m) return m;
    }
    return null;
  }

  structureAt(path: string, scopes: string[]): TargetStructure | null {
    const list = this.structures();
    for (const sc of [...scopes].reverse().concat([''])) {
      const s = list.find((x) => x.target === path && (x.scope ?? '') === sc);
      if (s?.statements.length) return s;
    }
    return null;
  }

  private contentPaths = computed(() => {
    const set = new Set<string>();
    const add = (p: string) => {
      const parts = p.split('.');
      for (let i = 1; i <= parts.length; i++) set.add(parts.slice(0, i).join('.'));
    };
    this.mappings().forEach((m) => add(m.target));
    this.structures().forEach((s) => add(s.target));
    return set;
  });

  // ---------------------------------------------------------------- rows
  private loopFor(st: Statement, ctx: LoopRef[]): LoopRef | null {
    if (!st.select?.trim() && st.inputs[0]) {
      return { sid: st.inputs[0].source_id, segs: treeSegs(st.inputs[0].path) };
    }
    return resolvePath(st.select ?? '', ctx, this.sourceIds());
  }

  private buildRows(): TreeRow[] {
    const rows: TreeRow[] = [];
    const collapsed = this.targetCollapsed();
    const content = this.contentPaths();

    const base0 = (n: FieldNode, depth: number, scopes: string[], ctx: LoopRef[], hidden: boolean) => ({
      node: n, depth, scopes, scope: scopes[scopes.length - 1] ?? '', ctx, hidden,
      inherited: false, mapping: null, stmt: null, branchIndex: -1, branchKey: '', hasContent: true,
      choiceGroup: n.choice ?? null, excluded: false, implied: false, isCopy: false,
    });

    /** Rows under a Copy-Of: each target child shows the source sub-path it is filled from
     * (matched by name, BIC -> BICFI style prefixes too). Explicitly mapped children override. */
    const copied = (parent: FieldNode, src: FieldNode, base: string, depth: number, scopes: string[], ctx: LoopRef[], hidden: boolean) =>
      copyPairs(parent, src).forEach(({ tc: n, sc, fuzzy }) => {
        if (this.mappingAt(n.path, scopes) || this.structureAt(n.path, scopes)) {
          wrapped(n, this.structureAt(n.path, scopes)?.statements ?? [], 0, depth, scopes, ctx, hidden);
          return;
        }
        const scope = scopes[scopes.length - 1] ?? '';
        const key = `e|${n.path}|${scope}`;
        const attrsOnly = n.children.length > 0 && !hasElementChildren(n);
        const isCollapsed = collapsed.has(key) && !attrsOnly;
        const formula = sc ? `${base}/${tagOf(sc)}` : '';
        rows.push({
          ...base0(n, depth, scopes, ctx, hidden), key, kind: 'element', label: tagOf(n), formula,
          expandable: n.children.length > 0 && !attrsOnly, collapsed: isCollapsed, hasContent: !!sc, implied: !!sc, fuzzy,
        });
        if (n.children.length && sc) copied(n, sc, formula, depth + 1, scopes, ctx, hidden || isCollapsed);
      });

    const nodes = (list: FieldNode[], depth: number, scopes: string[], ctx: LoopRef[], hidden: boolean) =>
      list.forEach((n) => wrapped(n, this.structureAt(n.path, scopes)?.statements ?? [], 0, depth, scopes, ctx, hidden));

    const base = base0;
    const statementRow = (key: string, kind: RowKind, label: string, formula: string, st: Statement, b: ReturnType<typeof base0>,
                          extra: Partial<TreeRow> = {}): boolean => {
      const isCollapsed = collapsed.has(key);
      rows.push({ ...b, key, kind, label, formula, stmt: st, expandable: true, collapsed: isCollapsed, ...extra });
      return isCollapsed;
    };

    const wrapped = (n: FieldNode, stmts: Statement[], i: number, depth: number, scopes: string[], ctx: LoopRef[], hidden: boolean) => {
      if (i >= stmts.length) {
        element(n, depth, scopes, ctx, hidden);
        return;
      }
      const st = stmts[i];
      const tag = tagOf(n);
      const b = base(n, depth, scopes, ctx, hidden);
      if (st.kind === 'for-each' || st.kind === 'for-each-group') {
        const label = st.kind === 'for-each' ? `${tag} - [For-Each]` : `${tag} - [For-Each-Group]`;
        const c = statementRow(`s|${st.id}`, st.kind, label, displaySelect(st), st, b);
        const loop = this.loopFor(st, ctx);
        wrapped(n, stmts, i + 1, depth + 1, scopes, loop ? [...ctx, loop] : ctx, hidden || c);
      } else if (st.kind === 'if') {
        const c = statementRow(`s|${st.id}`, 'if', `${tag} - [If]`, displayTest(st.test, st), st, b);
        wrapped(n, stmts, i + 1, depth + 1, scopes, ctx, hidden || c);
      } else {
        const c = statementRow(`s|${st.id}`, 'choose', `${tag} - [Choose]`, '', st, b);
        st.whens.forEach((w, k) => {
          const bk = branchKey(st, k);
          const wc = statementRow(`w|${st.id}|${bk}`, 'when', '[When]', displayTest(w.test, st), st,
            base(n, depth + 1, scopes, ctx, hidden || c), { branchIndex: k, branchKey: bk });
          wrapped(n, stmts, i + 1, depth + 2, [...scopes, bk], ctx, hidden || c || wc);
        });
        if (st.otherwise !== null) {
          const ok = otherwiseKey(st);
          const oc = statementRow(`o|${st.id}`, 'otherwise', '[Otherwise]', '', st,
            base(n, depth + 1, scopes, ctx, hidden || c), { branchKey: ok });
          wrapped(n, stmts, i + 1, depth + 2, [...scopes, ok], ctx, hidden || c || oc);
        }
      }
    };

    const choiceSel = this.target().choice_selections ?? {};
    const element = (n: FieldNode, depth: number, scopes: string[], ctx: LoopRef[], hidden: boolean) => {
      const scope = scopes[scopes.length - 1] ?? '';
      const excluded = !!n.choice && !!choiceSel[n.choice] && choiceSel[n.choice] !== n.path;
      const key = `e|${n.path}|${scope}`;
      const m = this.mappingAt(n.path, scopes);
      // An element whose only children are attributes (InstdAmt + @Ccy) always shows them.
      const attrsOnly = n.children.length > 0 && !hasElementChildren(n);
      const isCollapsed = collapsed.has(key) && !attrsOnly;
      const isCopy = this.isCopyMapping(m, n, ctx);
      rows.push({
        ...base(n, depth, scopes, ctx, hidden), key, kind: 'element', label: tagOf(n),
        formula: m ? displayMappingFormula(m.transform, m.inputs) : '',
        inherited: !!m && (m.scope ?? '') !== scope, mapping: m,
        expandable: n.children.length > 0 && !excluded && !attrsOnly, collapsed: isCollapsed || excluded,
        hasContent: content.has(n.path) && !excluded, excluded, isCopy,
      });
      if (!n.children.length) return;
      if (isCopy) {
        const formula = displayMappingFormula(m!.transform, m!.inputs);
        const loop = resolvePath(formula, ctx, this.sourceIds());
        const src = loop ? this.sourceNodeAt(loop) : null;
        if (src) copied(n, src, formula, depth + 1, scopes, ctx, hidden || isCollapsed || excluded);
        return;
      }
      nodes(n.children, depth + 1, scopes, ctx, hidden || isCollapsed || excluded);
    };

    nodes(this.target().fields, 0, [], [], false);
    return rows;
  }

  /** Copy-Of explicitly, or a plain source path mapped onto an element with children. */
  isCopyMapping(m: MappingRule | null, n: FieldNode, ctx: LoopRef[]): boolean {
    if (!m) return false;
    if (m.mode === 'copy-of') return true;
    if (!hasElementChildren(n)) return false;
    const f = displayMappingFormula(m.transform, m.inputs);
    return !!f && resolvePath(f, ctx, this.sourceIds()) !== null;
  }

  /** Sample input per source (Test / Run), shared with the Validate screen. */
  readonly sampleInputs: Record<string, string> = {};

  /** Expands every ancestor of a target field and selects its row. */
  revealTarget(path: string): void {
    const parts = path.split('.');
    const next = new Set(this.targetCollapsed());
    for (let i = 1; i < parts.length; i++) {
      const anc = parts.slice(0, i).join('.');
      [...next].forEach((k) => { if (k.split('|')[1] === anc) next.delete(k); });
    }
    this.targetCollapsed.set(next);
    const row = this.rows().find((r) => r.kind === 'element' && r.node.path === path);
    if (row) this.selectRow(row);
    this.bumpLayout();
    setTimeout(() => document.querySelector(`[data-row-key="${CSS.escape(row?.key ?? '')}"]`)
      ?.scrollIntoView({ block: 'center' }), 50);
  }

  /** Picks one alternative of an xs:choice (null clears the selection). */
  selectChoice(group: string, path: string | null): void {
    const sel = { ...(this.target().choice_selections ?? {}) };
    if (path) sel[group] = path;
    else delete sel[group];
    this.patchTarget({ choice_selections: sel });
    this.bumpLayout();
  }

  choiceAlternatives(group: string): FieldNode[] {
    return this.flatten(this.target().fields).filter((n) => n.choice === group);
  }

  // ---------------------------------------------------- custom functions
  addLibrary(lib: FunctionLibrary): void {
    this.libraries.update((list) => [...list, lib]);
  }

  renameLibrary(id: string, name: string): void {
    this.libraries.update((list) => list.map((l) => (l.id === id ? { ...l, name } : l)));
  }

  removeLibrary(id: string): void {
    this.libraries.update((list) => list.filter((l) => l.id !== id));
  }

  // ------------------------------------------------------- formula edits
  /** Sets an element row's formula (mapping) in that row's scope. Empty clears it. */
  setFormula(path: string, scope: string, text: string, mode?: 'value' | 'copy-of'): void {
    this.mappings.update((list) => {
      const idx = list.findIndex((m) => m.target === path && (m.scope ?? '') === scope);
      if (!text.trim() && !mode) return idx >= 0 ? list.filter((_, i) => i !== idx) : list;
      if (idx >= 0) {
        const cur = list[idx];
        return list.map((m, i) => (i === idx ? { ...cur, transform: text, inputs: [], mode: mode ?? cur.mode, note: null } : m));
      }
      const rule: MappingRule = {
        id: newId('m'), target: path, inputs: [], transform: text, for_each: false, origin: 'manual', scope, mode: mode ?? 'value',
      };
      return [...list, rule];
    });
  }

  setRowFormula(row: TreeRow, text: string): void {
    if (row.kind === 'element' && hasElementChildren(row.node) && resolvePath(text, row.ctx, this.sourceIds())) {
      this.setFormula(row.node.path, row.scope, text, 'copy-of');  // a whole element: copy it
    } else if (row.kind === 'element') {
      this.setFormula(row.node.path, row.scope, text, row.mapping?.mode === 'copy-of' && row.mapping.scope === row.scope ? 'copy-of' : undefined);
    } else if (row.stmt && (row.kind === 'for-each' || row.kind === 'for-each-group')) {
      this.updateStatementById(row.stmt.id, { select: text });
    } else if (row.stmt && row.kind === 'if') {
      this.updateStatementById(row.stmt.id, { test: text });
    } else if (row.stmt && row.kind === 'when') {
      const st = normalizeStatement(row.stmt);
      this.updateStatementById(st.id, { ...st, whens: st.whens.map((w, i) => (i === row.branchIndex ? { ...w, test: text } : w)) });
    }
  }

  setRowMode(row: TreeRow, mode: 'value' | 'copy-of'): void {
    this.setFormula(row.node.path, row.scope, row.formula, mode);
  }

  /** Path text for a source field dropped on / inserted at a row. */
  refFor(row: TreeRow | null, sid: string, treePath: string): string {
    return refText(sid, treePath, row?.ctx ?? []);
  }

  /** Drop of a source field onto a target row (replaces that row's formula). */
  dropOnRow(row: TreeRow, sid: string, treePath: string): string {
    const src = this.findSourceNode(sid, treePath);
    if (row.kind === 'element' && src?.children.length && row.node.children.length) {
      const n = this.mapContainer(row, sid, src);
      return n ? `Mapped ${n} child field(s) by name.` : 'No child names matched.';
    }
    if (row.kind === 'choose' || row.kind === 'otherwise') return 'Drop onto a [When] or the element instead.';
    this.setRowFormula(row, this.refFor(row, sid, treePath));
    return '';
  }

  /** Container onto container: for-each when both repeat, then children matched by name. */
  mapContainer(row: TreeRow, sid: string, src: FieldNode): number {
    let count = 0;
    const scope = row.scope;
    const walk = (s: FieldNode, t: FieldNode, ctx: LoopRef[], scopes: string[]) => {
      let inner = ctx;
      if (s.type === 'array' && t.type === 'array' && !(this.structureAt(t.path, scopes)?.statements ?? []).some((x) => x.kind === 'for-each' || x.kind === 'for-each-group')) {
        this.addStatementOn(t.path, scopes, 'for-each', refText(sid, s.path, ctx));
        inner = [...ctx, { sid, segs: treeSegs(s.path) }];
      }
      // Element with attributes and its own value (InstdAmt + @Ccy): map the value too.
      const simple = (n: FieldNode) => n.type !== 'object' && n.type !== 'array' && !hasElementChildren(n);
      if (simple(s) && simple(t) && !this.mappingAt(t.path, scopes)) {
        this.setFormula(t.path, scope, t === row.node ? refText(sid, s.path, ctx) : refText(sid, s.path, inner));
        count += 1;
      }
      for (const { tc, sc } of copyPairs(t, s)) {
        if (!sc) continue;
        if (tc.children.length && sc.children.length) walk(sc, tc, inner, scopes);
        else if (!tc.children.length && !sc.children.length && !this.mappingAt(tc.path, scopes)) {
          this.setFormula(tc.path, scope, refText(sid, sc.path, inner));
          count += 1;
        }
      }
    };
    walk(src, row.node, row.ctx, row.scopes);
    return count;
  }

  // ------------------------------------------------------------ statements
  private findStatement(id: string): { struct: TargetStructure; st: Statement } | null {
    for (const struct of this.structures()) {
      const st = struct.statements.find((s) => s.id === id);
      if (st) return { struct, st };
    }
    return null;
  }

  private putStatements(target: string, scope: string, statements: Statement[]): void {
    this.structures.update((list) => {
      const rest = list.filter((s) => !(s.target === target && (s.scope ?? '') === scope));
      return statements.length ? [...rest, { target, scope, statements }] : rest;
    });
  }

  private addStatementOn(path: string, scopes: string[], kind: StatementKind, formula = ''): Statement {
    const existing = this.structureAt(path, scopes);
    const scope = existing ? existing.scope ?? '' : scopes[scopes.length - 1] ?? '';
    const st: Statement = {
      id: newId('st'), kind, inputs: [], select: kind === 'for-each' || kind === 'for-each-group' ? formula : '',
      group_by: '',
      test: kind === 'if' ? formula : '',
      whens: kind === 'choose' ? [{ id: newId('w'), test: formula, value: '' }] : [],
      otherwise: kind === 'choose' ? '' : null,
    };
    this.putStatements(path, scope, [...(existing?.statements ?? []), st]);
    return st;
  }

  /** "Surround with …": the new statement goes closest to the element.
   * Surround with Choice moves the element's current mappings into the first [When]. */
  surround(row: TreeRow, kind: StatementKind | 'copy-of'): Statement | null {
    if (kind === 'copy-of') {
      this.setFormula(row.node.path, row.scope, row.formula || (row.ctx.length ? '.' : ''), 'copy-of');
      return null;
    }
    const st = this.addStatementOn(row.node.path, row.scopes, kind);
    if (kind === 'choose') {
      const from = row.scope;
      const to = branchKey(st, 0);
      this.mappings.update((list) => list.map((m) =>
        inSubtree(m.target, row.node.path) && (m.scope ?? '') === from ? { ...m, scope: to } : m));
      this.structures.update((list) => list.map((s) =>
        s.target !== row.node.path && inSubtree(s.target, row.node.path) && (s.scope ?? '') === from ? { ...s, scope: to } : s));
    }
    this.bumpLayout();
    return st;
  }

  updateStatementById(id: string, patch: Partial<Statement>): void {
    const found = this.findStatement(id);
    if (!found) return;
    const st = { ...normalizeStatement(found.st), ...patch };
    this.putStatements(found.struct.target, found.struct.scope ?? '',
      found.struct.statements.map((s) => (s.id === id ? st : s)));
  }

  removeStatementById(id: string): void {
    const found = this.findStatement(id);
    if (!found) return;
    const { struct, st } = found;
    this.putStatements(struct.target, struct.scope ?? '', struct.statements.filter((s) => s.id !== id));
    if (st.kind === 'choose') {
      // Keep the first branch's mappings as the element's own; drop the other branches.
      const keep = branchKey(st, 0);
      const back = struct.scope ?? '';
      this.mappings.update((list) => list.map((m) => ((m.scope ?? '') === keep ? { ...m, scope: back } : m)));
      this.structures.update((list) => list.map((s) => ((s.scope ?? '') === keep ? { ...s, scope: back } : s)));
      this.gcScopes();
    }
    this.bumpLayout();
  }

  moveStatementById(id: string, delta: -1 | 1): void {
    const found = this.findStatement(id);
    if (!found) return;
    const list = [...found.struct.statements];
    const i = list.findIndex((s) => s.id === id);
    const j = i + delta;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    this.putStatements(found.struct.target, found.struct.scope ?? '', list);
  }

  addWhen(id: string): void {
    const found = this.findStatement(id);
    if (found) this.updateStatementById(id, { whens: [...found.st.whens, { id: newId('w'), test: '', value: '' }] });
  }

  removeWhen(id: string, index: number): void {
    const found = this.findStatement(id);
    if (!found || found.st.whens.length <= 1) return;
    const key = branchKey(found.st, index);
    this.updateStatementById(id, { whens: found.st.whens.filter((_, i) => i !== index) });
    this.mappings.update((list) => list.filter((m) => (m.scope ?? '') !== key));
    this.structures.update((list) => list.filter((s) => (s.scope ?? '') !== key));
    this.gcScopes();
  }

  setOtherwise(id: string, on: boolean): void {
    const found = this.findStatement(id);
    if (!found) return;
    this.updateStatementById(id, { otherwise: on ? '' : null });
    if (!on) {
      const key = otherwiseKey(found.st);
      this.mappings.update((list) => list.filter((m) => (m.scope ?? '') !== key));
      this.structures.update((list) => list.filter((s) => (s.scope ?? '') !== key));
      this.gcScopes();
    }
  }

  /** Drops mappings/statements whose choose branch no longer exists. */
  private gcScopes(): void {
    const live = new Set<string>(['']);
    this.structures().forEach((s) => s.statements.forEach((st) => {
      if (st.kind !== 'choose') return;
      st.whens.forEach((_, i) => live.add(branchKey(st, i)));
      if (st.otherwise !== null) live.add(otherwiseKey(st));
    }));
    this.mappings.update((list) => list.filter((m) => live.has(m.scope ?? '')));
    this.structures.update((list) => list.filter((s) => live.has(s.scope ?? '')));
  }

  /** Clears the row: an element's mapping, or removes a statement. */
  clearRow(row: TreeRow): void {
    if (row.kind === 'element') this.setFormula(row.node.path, row.scope, '');
    else if (row.kind === 'when' && row.stmt) this.removeWhen(row.stmt.id, row.branchIndex);
    else if (row.kind === 'otherwise' && row.stmt) this.setOtherwise(row.stmt.id, false);
    else if (row.stmt) this.removeStatementById(row.stmt.id);
  }

  // ------------------------------------------------------------ mappings
  /** Legacy input-chip mapping (sheet import, AI chat, click-to-map). */
  addMapping(input: SourceRef, targetPath: string, origin: MappingRule['origin']): void {
    this.mappings.update((list) => {
      const existing = list.find((m) => m.target === targetPath && !(m.scope ?? ''));
      if (existing) {
        if (existing.inputs.some((i) => sameRef(i, input))) return list;
        const inputs = [...existing.inputs, input];
        const transform =
          inputs.length > 1 && !existing.transform.trim()
            ? `CONCAT(${inputs.map((_, i) => `{${i}}`).join(", ' ', ")})`
            : existing.transform;
        return list.map((m) => (m === existing ? { ...m, inputs, transform, origin } : m));
      }
      return [...list, { id: newId('m'), target: targetPath, inputs: [input], transform: '', for_each: false, origin, scope: '' }];
    });
  }

  removeMapping(id: string): void {
    const rule = this.mappings().find((m) => m.id === id);
    if (rule && this.detailTarget() === rule.target) this.detailTarget.set(null);
    this.mappings.update((list) => list.filter((m) => m.id !== id));
  }

  updateMapping(id: string, patch: Partial<MappingRule>): void {
    this.mappings.update((list) => list.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }

  removeMappingInput(id: string, index: number): void {
    this.mappings.update((list) =>
      list
        .map((m) => (m.id === id ? { ...m, inputs: m.inputs.filter((_, i) => i !== index) } : m))
        .filter((m) => m.inputs.length > 0 || m.transform.trim()),
    );
  }

  clearMappings(): void {
    this.mappings.set([]);
    this.structures.set([]);
    this.detailTarget.set(null);
    this.selectedRowKey.set(null);
  }

  /** Every target that reads this source field (from the resolved links). */
  usagesOf(ref: SourceRef): { target: string; kind: string; rowKey: string }[] {
    return this.links()
      .filter((l) => l.source_id === ref.source_id && l.source_path === ref.path)
      .map((l) => ({ target: l.target, kind: l.kind, rowKey: l.row_key }));
  }

  // ------------------------------------------------------------ variables
  addVariable(): void {
    varIdSeq += 1;
    this.variables.update((list) => [...list, { id: `v${varIdSeq}`, name: `var${varIdSeq}`, inputs: [], transform: '' }]);
  }

  removeVariable(id: string): void {
    this.variables.update((list) => list.filter((v) => v.id !== id));
  }

  updateVariable(id: string, patch: Partial<VariableRule>): void {
    this.variables.update((list) => list.map((v) => (v.id === id ? { ...v, ...patch } : v)));
  }

  addVariableInput(id: string, input: SourceRef): void {
    this.variables.update((list) =>
      list.map((v) =>
        v.id === id && !v.inputs.some((i) => sameRef(i, input)) ? { ...v, inputs: [...v.inputs, input] } : v,
      ),
    );
  }

  removeVariableInput(id: string, index: number): void {
    this.variables.update((list) =>
      list.map((v) => (v.id === id ? { ...v, inputs: v.inputs.filter((_, i) => i !== index) } : v)),
    );
  }

  // ------------------------------------------------------------- sessions
  /** Everything needed to resume work later. Secrets (API key, header values) only if asked. */
  exportSession(includeSecrets: boolean): SessionFile {
    const llm = this.llm();
    return {
      format: 'mapsheet-ai-session', version: 1, name: this.sessionName(), saved_at: new Date().toISOString(),
      state: {
        sources: this.sources().map((src) => ({ ...src, collapsed: [...src.collapsed] })),
        target: { ...this.target(), collapsed: [...this.target().collapsed] },
        mappings: this.mappings(),
        variables: this.variables(),
        root_condition: this.rootCondition(),
        structures: this.structures(),
        project: this.project(),
        llm: includeSecrets ? llm : {
          ...llm, custom_key: llm.custom_key ? '' : llm.custom_key,
          custom_headers: (llm.custom_headers ?? []).map((h) => ({ name: h.name, value: '' })),
        },
        libraries: this.libraries(),
        sample_inputs: { ...this.sampleInputs },
        target_collapsed: [...this.targetCollapsed()],
        line_mode: this.lineMode(),
      },
    };
  }

  /** Replaces the whole workspace with a saved session. Throws on a file that isn't a session. */
  importSession(file: SessionFile): void {
    // 'datamapper-session' = files saved before the rename to MapSheet AI
    if ((file?.format !== 'mapsheet-ai-session' && file?.format !== 'datamapper-session') || !file.state) {
      throw new Error('Not a MapSheet AI session file.');
    }
    const st = file.state;
    const sources: UiSource[] = (st.sources ?? []).map((src) => ({ ...src, collapsed: new Set(src.collapsed ?? []) }));
    if (!sources.length) sources.push(newSource());
    this.sources.set(sources);
    sourceSeq = Math.max(sourceSeq, ...sources.map((src) => parseInt(src.id.replace(/\D/g, ''), 10) || 0));
    this.target.set({ ...st.target, collapsed: new Set(st.target?.collapsed ?? []) } as UiTarget);
    this.mappings.set(st.mappings ?? []);
    this.variables.set(st.variables ?? []);
    varIdSeq = Math.max(varIdSeq, ...(st.variables ?? []).map((v) => parseInt(v.id.replace(/\D/g, ''), 10) || 0));
    this.rootCondition.set(st.root_condition ?? { inputs: [], transform: '' });
    this.structures.set(st.structures ?? []);
    if (st.project) this.project.set(st.project);
    if (st.llm) {
      // keep secrets typed in this tab when the file doesn't carry them
      const cur = this.llm();
      this.llm.set({
        ...st.llm, provider: 'openai',
        custom_key: st.llm.custom_key || cur.custom_key,
        custom_headers: (st.llm.custom_headers ?? []).map((h) => ({
          name: h.name, value: h.value || (cur.custom_headers ?? []).find((c) => c.name === h.name)?.value || '',
        })),
      });
    }
    this.libraries.set(st.libraries ?? []);
    Object.keys(this.sampleInputs).forEach((k) => delete this.sampleInputs[k]);
    Object.assign(this.sampleInputs, st.sample_inputs ?? {});
    this.targetCollapsed.set(new Set(st.target_collapsed ?? []));
    if (st.line_mode) this.lineMode.set(st.line_mode);
    this.links.set([]);
    this.problems.set([]);
    this.selectedRowKey.set(null);
    this.detailTarget.set(null);
    this.selectedSource.set(null);
    this.sessionName.set(file.name || 'Untitled session');
    this.bumpLayout();
  }

  /** Starts over with an empty workspace (keeps LLM settings and custom functions). */
  resetSession(): void {
    sourceSeq = 0;
    this.sources.set([newSource()]);
    this.target.set({ type: 'jsonschema', fields: [], mandatory_overrides: {}, ready: false, raw: '', collapsed: new Set() });
    this.mappings.set([]);
    this.variables.set([]);
    this.rootCondition.set({ inputs: [], transform: '' });
    this.structures.set([]);
    Object.keys(this.sampleInputs).forEach((k) => delete this.sampleInputs[k]);
    this.targetCollapsed.set(new Set());
    this.links.set([]);
    this.problems.set([]);
    this.selectRow(null);
    this.selectedSource.set(null);
    this.sessionName.set('Untitled session');
  }

  // -------------------------------------------------------------- export
  /** The exact payload every backend endpoint expects. */
  toWorkspace(): MappingWorkspace {
    return {
      sources: this.sources().map((s) => ({ id: s.id, label: s.label, type: s.type, fields: s.fields, namespace: s.namespace ?? null })),
      target: {
        type: this.target().type, fields: this.target().fields,
        mandatory_overrides: this.target().mandatory_overrides, namespace: this.target().namespace ?? null,
        choice_selections: this.target().choice_selections ?? {},
      },
      mappings: this.mappings(),
      variables: this.variables(),
      root_condition: this.rootCondition(),
      structures: this.structures(),
      project: this.project(),
      jar_functions: this.jarFunctions(),
      custom_sources: this.libraries().filter((l) => l.kind === 'java' && l.source)
        .map((l) => ({ file_name: l.file_name, content: l.source! })),
      custom_jars: this.libraries().filter((l) => l.kind === 'jar').map((l) => l.file_name),
    };
  }

  flatten(nodes: FieldNode[]): FieldNode[] {
    const out: FieldNode[] = [];
    const walk = (list: FieldNode[]) => list.forEach((n) => { out.push(n); walk(n.children); });
    walk(nodes);
    return out;
  }

  sourceLabel(id: string): string {
    return this.sources().find((s) => s.id === id)?.label ?? id;
  }
}

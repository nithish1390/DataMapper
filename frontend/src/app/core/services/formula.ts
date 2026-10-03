import { SourceRef, Statement } from '../models/api.models';

/** An active for-each: iterating source `sid` at name segments `segs`. */
export interface LoopRef {
  sid: string;
  segs: string[];
}

/** 'Document.PmtInf[].PmtInfId' -> ['Document', 'PmtInf', 'PmtInfId'] */
export function treeSegs(path: string): string[] {
  return path.split('.').filter(Boolean).map((s) => s.replace(/\[\]$/, ''));
}

export function absRef(sid: string, path: string): string {
  return `$${sid}/${treeSegs(path).join('/')}`;
}

/** The path text to insert for a source field, relative to the
 * innermost for-each item when it lives under it (Name/FullName, ../X, .),
 * absolute ($s1/Document/...) otherwise. */
export function refText(sid: string, treePath: string, ctx: LoopRef[]): string {
  const segs = treeSegs(treePath);
  const loop = ctx[ctx.length - 1];
  if (loop && loop.sid === sid) {
    let k = 0;
    while (k < loop.segs.length && k < segs.length && loop.segs[k] === segs[k]) k++;
    if (k === loop.segs.length) return segs.slice(k).join('/') || '.';
    if (k >= 1) return [...Array(loop.segs.length - k).fill('..'), ...segs.slice(k)].join('/');
  }
  return `$${sid}/${segs.join('/')}`;
}

/** Resolves a simple path formula (a for-each select) to the loop it opens. */
export function resolvePath(text: string, ctx: LoopRef[], sourceIds: string[]): LoopRef | null {
  const t = text.trim().replace(/\[[^\]]*\]/g, '');
  if (!t || /[()\s,'"]/.test(t)) return null;
  const first = sourceIds[0] ?? '';
  let sid: string;
  let base: string[];
  let rest: string;
  const abs = /^\$([\w-]+)\/(.*)$/.exec(t);
  if (abs) {
    sid = sourceIds.includes(abs[1]) ? abs[1] : first;
    base = [];
    rest = abs[2];
  } else if (t.startsWith('/')) {
    sid = first;
    base = [];
    rest = t.slice(1);
  } else {
    const loop = ctx[ctx.length - 1];
    sid = loop?.sid ?? first;
    base = loop ? [...loop.segs] : [];
    rest = t;
  }
  for (const step of rest.split('/').filter(Boolean)) {
    if (step === '.') continue;
    if (step === '..') base.pop();
    else base.push(step.split(':').pop()!);
  }
  return { sid, segs: base };
}

/** Legacy {0}/{1} input chips -> path text, so every formula reads the same. */
export function substitutePlaceholders(text: string, inputs: SourceRef[]): string {
  return text.replace(/\{(\d+)\}/g, (m, i) => {
    const inp = inputs[+i];
    return inp ? absRef(inp.source_id, inp.path) : m;
  });
}

export function displayMappingFormula(transform: string, inputs: SourceRef[]): string {
  const t = transform.trim() || (inputs.length ? '{0}' : '');
  return substitutePlaceholders(t, inputs);
}

export function displaySelect(st: Statement): string {
  if (st.select?.trim()) return st.select;
  return st.inputs[0] ? absRef(st.inputs[0].source_id, st.inputs[0].path) : '';
}

export function displayTest(text: string, st: Statement): string {
  if (!text.trim()) return st.inputs[0] ? absRef(st.inputs[0].source_id, st.inputs[0].path) : '';
  return substitutePlaceholders(text, st.inputs);
}

/** A statement rewritten with no input chips (all placeholders spelled out as paths). */
export function normalizeStatement(st: Statement): Statement {
  if (!st.inputs.length) return st;
  return {
    ...st,
    select: displaySelect(st),
    test: st.kind === 'if' ? displayTest(st.test, st) : st.test,
    whens: st.whens.map((w) => ({ ...w, test: displayTest(w.test, st), value: substitutePlaceholders(w.value, st.inputs) })),
    otherwise: st.otherwise === null ? null : substitutePlaceholders(st.otherwise, st.inputs),
    inputs: [],
  };
}

export function branchKey(st: Statement, i: number): string {
  return `${st.id}:${st.whens[i]?.id || `w${i}`}`;
}

export function otherwiseKey(st: Statement): string {
  return `${st.id}:o`;
}

let uid = 0;
export function newId(prefix: string): string {
  uid += 1;
  return `${prefix}${Date.now().toString(36)}${uid}`;
}

export function isAttribute(n: { name: string }): boolean {
  return n.name.startsWith('@');
}

/** Real containers; an element whose only children are attributes holds a value (e.g. InstdAmt + @Ccy). */
export function hasElementChildren(n: { children: { name: string }[] }): boolean {
  return n.children.some((c) => !c.name.startsWith('@'));
}

const bareName = (n: { name: string }) => n.name.replace(/\[\]$/, '');

/** Copy-Of / drop-by-name pairing, same rules as the backend: exact name first, then a unique
 * source child whose name is a prefix of the target's (or vice versa), e.g. BIC -> BICFI. */
export function copyPairs<T extends { name: string; children: { name: string }[] }>(tgt: T, src: T):
    { tc: T; sc: T | null; fuzzy: boolean }[] {
  const tChildren = tgt.children as unknown as T[];
  const sChildren = src.children as unknown as T[];
  const byName = new Map(sChildren.map((c) => [bareName(c), c]));
  const used = new Set<string>();
  const pairs = tChildren.map((tc) => {
    const sc = byName.get(bareName(tc)) ?? null;
    if (sc) used.add(bareName(sc));
    return { tc, sc, fuzzy: false };
  });
  const spare = sChildren.filter((c) => !used.has(bareName(c)));
  const kind = (n: T) => (isAttribute(n) ? 'attr' : hasElementChildren(n) ? 'group' : 'value');
  for (const p of pairs) {
    if (p.sc) continue;
    const t = bareName(p.tc).replace(/^@/, '').toLowerCase();
    const cands = spare.filter((c) => {
      const n = bareName(c).replace(/^@/, '').toLowerCase();
      return kind(c) === kind(p.tc) && Math.min(t.length, n.length) >= 3 && (t.startsWith(n) || n.startsWith(t));
    });
    if (cands.length === 1) {
      p.sc = cands[0];
      p.fuzzy = true;
      spare.splice(spare.indexOf(cands[0]), 1);
    }
  }
  return pairs;
}

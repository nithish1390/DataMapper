import { WorkspaceService } from './workspace.service';

/** The mapping as it appears in the target tree, as sheet rows (header first): one row per mapped
 * field, statement (For-Each, Choice / When / Otherwise, If) and variable, with its formula, the source
 * fields it reads (from the resolved links) and the statements it sits in. */
export function mappingSheet(ws: WorkspaceService): string[][] {
  const rows = ws.rows();
  const stmtKinds = ['for-each', 'for-each-group', 'if', 'choose', 'when', 'otherwise', 'local-variable', 'variable'];
  const xpath = (dotted: string) => '/' + dotted.replace(/\[\]/g, '').split('.').join('/');
  const overrides = ws.target().mandatory_overrides ?? {};
  const sources = new Map<string, string[]>();
  for (const l of ws.links()) {
    const list = sources.get(l.row_key) ?? [];
    const ref = `$${l.source_id}${xpath(l.source_path)}`;
    if (!list.includes(ref)) list.push(ref);
    sources.set(l.row_key, list);
  }
  const kindLabel = (r: (typeof rows)[number]): string => {
    switch (r.kind) {
      case 'for-each': return 'For-Each';
      case 'for-each-group': return 'For-Each-Group';
      case 'if': return 'If';
      case 'choose': return 'Choice';
      case 'when': return 'When';
      case 'otherwise': return 'Otherwise';
      case 'variable': return `Global variable (${r.variable?.var_type ?? 'string'})`;
      case 'local-variable': return `Variable (${r.stmt?.var_type ?? 'string'})`;
      default: return r.implied ? 'Copy-Of (from parent)' : r.isCopy ? 'Copy-Of' : 'Value';
    }
  };
  const out: string[][] = [['Target Path', 'Target Field', 'Kind', 'Mapping / Formula', 'Source Fields', 'Inside',
    'Mandatory', 'Data Type']];
  const rc = ws.rootCondition();
  if (rc.transform.trim()) out.push(['/', '(root)', 'Root condition', rc.transform, '', '', '', '']);
  const formula = (r: (typeof rows)[number]): string =>
    r.kind === 'for-each-group' && r.stmt?.group_by ? `${r.formula ?? ''}  group by ${r.stmt.group_by}` : r.formula ?? '';
  const dataType = (r: (typeof rows)[number]): string => {
    const t = r.node.type === 'array' ? 'repeating' : r.node.type;
    return r.node.start ? `${t} (${r.node.start}–${r.node.start + (r.node.length ?? 1) - 1})` : t;
  };
  const stack: { depth: number; text: string }[] = [];
  for (const r of rows) {
    while (stack.length && stack[stack.length - 1].depth >= r.depth) stack.pop();
    const inside = stack.map((x) => x.text).join(' › ');
    const isStmt = stmtKinds.includes(r.kind);
    if (r.kind !== 'var-header' && (isStmt || (r.formula ?? '').trim())) {
      const name = r.kind === 'variable' || r.kind === 'local-variable' ? `$${r.label.replace(' - [Variable]', '').replace(/^\$/, '')}`
        : r.node.name.replace('[]', '');
      out.push([
        r.kind === 'variable' ? '' : xpath(r.node.path),
        name,
        kindLabel(r) + (r.excluded ? ' (choice not selected: not written)' : ''),
        formula(r),
        (sources.get(r.key) ?? []).join('; '),
        inside,
        r.kind === 'element' ? ((overrides[r.node.path] ?? r.node.mandatory) ? 'Yes' : 'No') : '',
        r.kind === 'element' ? dataType(r) : '',
      ]);
    }
    if (['for-each', 'for-each-group', 'if', 'when', 'otherwise'].includes(r.kind)) {
      const label = kindLabel(r) + (r.kind === 'otherwise' ? '' : ` ${formula(r)}`.trimEnd());
      stack.push({ depth: r.depth, text: `[${label}]` });
    }
  }
  return out;
}

/** CSV with a BOM (so Excel reads it as UTF-8) and quoted cells where needed. */
export function toCsvText(rows: string[][]): string {
  const cell = (v: string) => (/[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return '\ufeff' + rows.map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n';
}

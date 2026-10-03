import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, ViewChild, effect, signal } from '@angular/core';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ApiService } from '../../../../core/services/api.service';
import { MappingLink } from '../../../../core/models/api.models';


interface Line {
  d: string;
  x1: number; y1: number; x2: number; y2: number;
  color: string;
  width: number;
  opacity: number;
  dashed: boolean;
}

const KIND_COLOR: Record<string, string> = {
  'value-of': 'var(--wire)',
  'copy-of': 'var(--wire)',
  'for-each': 'var(--accent)',
  'for-each-group': 'var(--accent)',
  if: 'var(--wire-ai)',
  when: 'var(--wire-ai)',
};

/** SVG overlay drawing source -> target mapping lines across the centre
 * column. Endpoints are found via the data-side /
 * data-path attributes on field-tree rows; collapsed fields fall back to
 * their nearest visible ancestor, and rows scrolled out of view are clamped
 * to the panel edge and drawn dashed. */
@Component({
  selector: 'app-mapping-lines',
  standalone: true,
  imports: [CommonModule],
  template: `
    <svg #svg style="position:absolute; inset:0; width:100%; height:100%; pointer-events:none; overflow:visible;">
      <g *ngFor="let l of lines()">
        <path [attr.d]="l.d" fill="none" [attr.stroke]="l.color" [attr.stroke-width]="l.width"
              [attr.stroke-opacity]="l.opacity" [attr.stroke-dasharray]="l.dashed ? '4 4' : null"/>
        <circle [attr.cx]="l.x1" [attr.cy]="l.y1" r="2.6" [attr.fill]="l.color" [attr.fill-opacity]="l.opacity"/>
        <circle [attr.cx]="l.x2" [attr.cy]="l.y2" r="2.6" [attr.fill]="l.color" [attr.fill-opacity]="l.opacity"/>
      </g>
    </svg>
  `,
  host: { style: 'position:absolute; inset:0; pointer-events:none; z-index:4;' },
})
export class MappingLinesComponent implements AfterViewInit, OnDestroy {
  @ViewChild('svg') svg!: ElementRef<SVGSVGElement>;
  lines = signal<Line[]>([]);

  private raf = 0;
  private observer?: MutationObserver;
  private onScroll = () => this.schedule();
  private linksTimer?: ReturnType<typeof setTimeout>;

  constructor(private host: ElementRef<HTMLElement>, private workspace: WorkspaceService, private zone: NgZone,
              private api: ApiService) {
    // Resolved links + per-row problems come from the backend. Re-checked on every change that can
    // affect them (mappings, statements, schemas, XSLT version, variables, functions…); responses that
    // arrive after a newer request are ignored, so the red markers always match the current state.
    let seq = 0;
    effect(() => {
      this.workspace.mappings();
      this.workspace.structures();
      this.workspace.target();
      this.workspace.sources();
      this.workspace.variables();
      this.workspace.rootCondition();
      this.workspace.project();
      this.workspace.libraries();
      this.workspace.analysisTick();
      const ready = this.workspace.target().ready && this.workspace.anySourceReady();
      clearTimeout(this.linksTimer);
      const mine = ++seq;
      if (!ready) {
        this.workspace.links.set([]);
        this.workspace.problems.set([]);
        return;
      }
      this.linksTimer = setTimeout(() => {
        this.api.analysis(this.workspace.toWorkspace()).subscribe({
          next: (res) => {
            if (mine !== seq) return;  // a newer check is on its way
            this.workspace.links.set(res.links);
            this.workspace.problems.set(res.problems);
          },
          error: () => undefined,
        });
      }, 200);
    }, { allowSignalWrites: true });
    effect(() => {
      this.workspace.links();
      this.workspace.visibleRows();
      this.workspace.lineMode();
      this.workspace.selectedRowKey();
      this.workspace.selectedSource();
      this.workspace.layoutTick();
      this.schedule();
    });
  }

  ngAfterViewInit(): void {
    const container = this.host.nativeElement.parentElement!;
    this.zone.runOutsideAngular(() => {
      this.observer = new MutationObserver((muts) => {
        if (muts.some((m) => !this.svg.nativeElement.contains(m.target))) this.schedule();
      });
      this.observer.observe(container, { childList: true, subtree: true });
      document.addEventListener('scroll', this.onScroll, true);
      window.addEventListener('resize', this.onScroll);
    });
    this.schedule();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
    document.removeEventListener('scroll', this.onScroll, true);
    window.removeEventListener('resize', this.onScroll);
    cancelAnimationFrame(this.raf);
  }

  private schedule(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.zone.run(() => this.compute());
    });
  }

  /** The row for a path, or its nearest rendered ancestor (collapsed parents). */
  private findRow(container: HTMLElement, side: string, path: string): HTMLElement | null {
    let p = path;
    while (p) {
      const el = container.querySelector<HTMLElement>(`.rail-scroll .tnode[data-side="${CSS.escape(side)}"][data-path="${CSS.escape(p)}"]`);
      if (el) return el;
      const cut = p.lastIndexOf('.');
      p = cut > 0 ? p.slice(0, cut) : '';
    }
    return null;
  }

  /** Target row for a link; falls back to the nearest visible ancestor element row. */
  private findTargetRow(container: HTMLElement, link: MappingLink): HTMLElement | null {
    const exact = container.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(link.row_key)}"]`);
    if (exact) return exact;
    let p = link.target;
    while (p) {
      const el =
        container.querySelector<HTMLElement>(`.tm-row[data-kind="element"][data-path="${CSS.escape(p)}"][data-scope="${CSS.escape(link.scope)}"]`) ??
        container.querySelector<HTMLElement>(`.tm-row[data-path="${CSS.escape(p)}"]`);
      if (el) return el;
      const cut = p.lastIndexOf('.');
      p = cut > 0 ? p.slice(0, cut) : '';
    }
    return null;
  }

  private compute(): void {
    const mode = this.workspace.lineMode();
    if (mode === 'none') {
      this.lines.set([]);
      return;
    }
    const container = this.host.nativeElement.parentElement!;
    const box = container.getBoundingClientRect();
    const row = this.workspace.selectedRow();
    const focusSource = this.workspace.selectedSource();
    const out: Line[] = [];

    for (const link of this.workspace.links()) {
      const focused =
        (!!row && (link.row_key === row.key ||
          (row.kind === 'element' && link.target.startsWith(`${row.node.path}.`) &&
           (!row.scope || link.scope === row.scope)))) ||
        (!!focusSource && focusSource.source_id === link.source_id && focusSource.path === link.source_path);
      if (mode === 'selected' && !focused) continue;

      const srcRow = this.findRow(container, link.source_id, link.source_path);
      const tgtRow = this.findTargetRow(container, link);
      if (!srcRow || !tgtRow) continue;
      const srcRail = srcRow.closest('.rail-scroll') as HTMLElement | null;
      const tgtRail = tgtRow.closest('.rail-scroll') as HTMLElement | null;
      if (!srcRail || !tgtRail) continue;

      const sr = srcRow.getBoundingClientRect();
      const tr = tgtRow.getBoundingClientRect();
      const sRail = srcRail.getBoundingClientRect();
      const tRail = tgtRail.getBoundingClientRect();
      const clamp = (y: number, r: DOMRect) => Math.min(Math.max(y, r.top + 4), r.bottom - 4);
      const sy = sr.top + sr.height / 2;
      const ty = tr.top + tr.height / 2;
      const offscreen = sy !== clamp(sy, sRail) || ty !== clamp(ty, tRail);

      const x1 = sRail.right - box.left;
      const y1 = clamp(sy, sRail) - box.top;
      const x2 = tRail.left - box.left;
      const y2 = clamp(ty, tRail) - box.top;
      const dx = Math.max(40, (x2 - x1) * 0.4);
      out.push({
        d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
        x1, y1, x2, y2,
        color: KIND_COLOR[link.kind] ?? 'var(--wire)',
        width: focused ? 2.2 : 1.2,
        opacity: focused ? 0.95 : row || focusSource ? 0.12 : 0.35,
        dashed: offscreen || link.kind !== 'value-of',
      });
    }
    out.sort((a, b) => a.width - b.width);
    this.lines.set(out);
  }
}

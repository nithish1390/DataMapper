import { CommonModule } from '@angular/common';
import { Component, Injectable, computed, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { FullValidation } from '../../../../core/models/api.models';

type ListKind = 'not-mapped' | 'mandatory' | 'optional' | 'problems' | 'xsd' | null;

@Injectable({ providedIn: 'root' })
export class ValidationService {
  readonly isOpen = signal(false);
  readonly loading = signal(false);
  readonly result = signal<FullValidation | null>(null);
  readonly error = signal<string | null>(null);

  constructor(private api: ApiService, private workspace: WorkspaceService) {}

  run(): void {
    this.isOpen.set(true);
    this.loading.set(true);
    this.error.set(null);
    const src = this.workspace.sources()[0];
    this.api.validateFull(this.workspace.toWorkspace(), this.workspace.target().raw ?? '', this.workspace.sampleInputs,
      src?.type === 'xsd' ? src.raw ?? '' : '')
      .subscribe({
        next: (r) => {
          this.result.set(r);
          this.loading.set(false);
          this.workspace.requestAnalysis();  // the tree's red markers re-check against the same state
        },
        error: (err) => {
          this.error.set(err.error?.detail ?? err.message);
          this.loading.set(false);
        },
      });
  }

  close(): void {
    this.isOpen.set(false);
  }
}

/** Validate screen: is the mapping valid against the target XSD, with a summary of
 * mapped / not mapped fields; click a number to list those fields and jump to them. */
@Component({
  selector: 'app-validation-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './validation-modal.component.html',
})
export class ValidationModalComponent {
  list = signal<ListKind>(null);
  filter = signal('');

  constructor(public v: ValidationService, private workspace: WorkspaceService) {
    // A failing XSD check opens its explained errors straight away.
    effect(() => {
      const r = this.v.result();
      if (r?.xsd.ran && !r.xsd.valid) this.list.set('xsd');
    }, { allowSignalWrites: true });
  }

  percent = computed(() => {
    const r = this.v.result();
    return r && r.total_fields ? Math.round((r.mapped_fields / r.total_fields) * 100) : 0;
  });

  xsdDetails = computed(() => {
    const r = this.v.result();
    const q = this.filter().trim().toLowerCase();
    const d = r?.xsd.details?.length ? r.xsd.details
      : (r?.xsd.errors ?? []).map((e) => ({ line: 0, message: e, target: '', formula: '', hint: '' }));
    return q ? d.filter((x) => (x.message + x.target + x.hint).toLowerCase().includes(q)) : d;
  });

  items = computed<{ path: string; note: string }[]>(() => {
    const r = this.v.result();
    if (!r) return [];
    const q = this.filter().trim().toLowerCase();
    let out: { path: string; note: string }[] = [];
    switch (this.list()) {
      case 'not-mapped':
        out = [...r.unmapped_mandatory.map((p) => ({ path: p, note: 'mandatory' })),
               ...r.unmapped_optional.map((p) => ({ path: p, note: 'optional' }))];
        break;
      case 'mandatory':
        out = r.unmapped_mandatory.map((p) => ({ path: p, note: 'mandatory' }));
        break;
      case 'optional':
        out = r.unmapped_optional.map((p) => ({ path: p, note: 'optional' }));
        break;
      case 'problems':
        out = r.problems.map((p) => ({ path: p.target, note: p.message }));
        break;
      case 'xsd':
        out = r.xsd.errors.map((e) => ({ path: '', note: e }));
        break;
    }
    return q ? out.filter((x) => (x.path + ' ' + x.note).toLowerCase().includes(q)) : out;
  });

  show(kind: ListKind): void {
    this.list.set(this.list() === kind ? null : kind);
    this.filter.set('');
  }

  goTo(path: string): void {
    if (!path) return;
    this.v.close();
    this.workspace.revealTarget(path);
  }

  short(path: string): string {
    return path.replace(/\[\]/g, '');
  }
}

import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FieldNode, SourceRef } from '../../../../core/models/api.models';
import { WorkspaceService } from '../../../../core/services/workspace.service';

export interface DragPayload {
  sourceId: string; // a source id, or 'target'
  path: string;
}

@Component({
  selector: 'app-field-tree',
  standalone: true,
  imports: [CommonModule, FieldTreeComponent],
  templateUrl: './field-tree.component.html',
})
export class FieldTreeComponent {
  /** 'target', or a source id */
  @Input({ required: true }) side!: string;
  @Input({ required: true }) nodes: FieldNode[] = [];
  @Input() depth = 0;
  @Input() collapsed = new Set<string>();
  @Input() mappedTargetPaths = new Set<string>();
  @Input() mappedSourceInputs = new Set<string>(); // `${sourceId}::${path}`
  @Input() problemPaths = new Set<string>();
  @Input() ancestorProblemPaths = new Set<string>();
  @Input() selectedSource: SourceRef | null = null;
  @Input() detailTarget: string | null = null;
  /** target path -> statement kinds ('for-each' | 'if' | 'choose' | 'copy-of'), outermost first */
  @Input() stmtBadges: Record<string, string[]> = {};

  @Output() nodeClick = new EventEmitter<FieldNode>();
  @Output() nodeMenu = new EventEmitter<{ node: FieldNode; event: MouseEvent }>();
  @Output() dropped = new EventEmitter<{ node: FieldNode; payload: DragPayload }>();
  @Output() toggleCollapse = new EventEmitter<string>();
  @Output() toggleMandatory = new EventEmitter<FieldNode>();
  @Output() renameField = new EventEmitter<FieldNode>();
  @Output() addChildField = new EventEmitter<FieldNode>();

  constructor(public workspace: WorkspaceService) {}

  isTarget = () => this.side === 'target';

  isCollapsed(node: FieldNode): boolean {
    return this.collapsed.has(node.path);
  }

  /** Type icon: ABC text, 123 integer, 1.2 decimal, T/F boolean, ▤ element. */
  icon(node: FieldNode): string {
    if (node.name.startsWith('@')) return '@';
    if (node.type === 'object' || node.type === 'array') return '▤';
    return { integer: '123', number: '1.2', boolean: 'T/F' }[node.type as string] ?? 'ABC';
  }

  hasChildren(node: FieldNode): boolean {
    return node.children.length > 0;
  }

  isUsed(node: FieldNode): boolean {
    if (this.isTarget()) return this.mappedTargetPaths.has(node.path);
    return this.mappedSourceInputs.has(`${this.side}::${node.path}`);
  }

  isSelected(node: FieldNode): boolean {
    return !this.isTarget() && this.selectedSource?.source_id === this.side && this.selectedSource?.path === node.path;
  }

  isProblem(node: FieldNode): boolean {
    return this.isTarget() && this.problemPaths.has(node.path);
  }

  isProblemAncestor(node: FieldNode): boolean {
    return this.isTarget() && !this.isProblem(node) && this.ancestorProblemPaths.has(node.path);
  }

  isDetailOpen(node: FieldNode): boolean {
    return this.isTarget() && this.detailTarget === node.path;
  }

  badgeLabel(kind: string): string {
    return { 'for-each': '↻ for-each', if: '? if', choose: '⑂ choose', 'copy-of': '⧉ copy-of' }[kind] ?? kind;
  }

  isMandatory(node: FieldNode): boolean {
    return this.workspace.isMandatory(node.path, node.mandatory);
  }

  onMenu(event: MouseEvent, node: FieldNode): void {
    if (!this.nodeMenu.observed) return;
    event.preventDefault();
    this.nodeMenu.emit({ node, event });
  }

  onDragStart(event: DragEvent, node: FieldNode): void {
    const payload: DragPayload = { sourceId: this.side, path: node.path };
    event.dataTransfer?.setData('text/plain', JSON.stringify(payload));
    event.dataTransfer!.effectAllowed = 'copy';
  }

  onDragOver(event: DragEvent): void {
    if (this.isTarget()) event.preventDefault();
  }

  onDrop(event: DragEvent, node: FieldNode): void {
    if (!this.isTarget()) return;
    event.preventDefault();
    const raw = event.dataTransfer?.getData('text/plain');
    if (!raw) return;
    try {
      const payload: DragPayload = JSON.parse(raw);
      if (payload.sourceId && payload.sourceId !== 'target') {
        this.dropped.emit({ node, payload });
      }
    } catch {
      /* ignore malformed drag payload */
    }
  }
}

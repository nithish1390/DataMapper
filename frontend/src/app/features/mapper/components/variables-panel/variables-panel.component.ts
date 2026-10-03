import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { DragPayload } from '../field-tree/field-tree.component';
import { FunctionMenuComponent } from '../mapping-canvas/function-menu.component';
import { ConfirmService } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-variables-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, FunctionMenuComponent],
  templateUrl: './variables-panel.component.html',
})
export class VariablesPanelComponent {
  openMenuFor: string | null = null;

  constructor(public workspace: WorkspaceService, private confirm: ConfirmService) {}

  async remove(id: string, name: string): Promise<void> {
    if (await this.confirm.ask(`Delete the variable $${name}? Formulas using it will evaluate to empty.`)) {
      this.workspace.removeVariable(id);
    }
  }

  async removeInput(id: string, index: number): Promise<void> {
    if (await this.confirm.ask('Remove this source input from the variable?')) this.workspace.removeVariableInput(id, index);
  }

  add(): void {
    this.workspace.addVariable();
  }

  onDrop(event: DragEvent, id: string): void {
    event.preventDefault();
    const raw = event.dataTransfer?.getData('text/plain');
    if (!raw) return;
    try {
      const payload: DragPayload = JSON.parse(raw);
      if (payload.sourceId && payload.sourceId !== 'target') {
        this.workspace.addVariableInput(id, { source_id: payload.sourceId, path: payload.path });
      }
    } catch {
      /* ignore */
    }
  }

  insertFn(id: string, template: string): void {
    this.workspace.updateVariable(id, { transform: template });
    this.openMenuFor = null;
  }
}

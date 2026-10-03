import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { WorkspaceService } from '../../../../core/services/workspace.service';

interface FnItem {
  label: string;
  template: string;
  title?: string;
}

const BUILTIN_FUNCTIONS: FnItem[] = [
  { label: 'COPY (direct)', template: 'COPY({0})' },
  { label: 'CONCAT', template: "CONCAT({0}, {1})" },
  { label: 'UPPERCASE', template: 'UPPERCASE({0})' },
  { label: 'LOWERCASE', template: 'LOWERCASE({0})' },
  { label: 'TRIM (normalize-space)', template: 'TRIM({0})' },
  { label: 'SUBSTRING', template: 'SUBSTRING({0}, 0, 5)' },
  { label: 'REPLACE', template: "REPLACE({0}, '-', '')" },
  { label: 'CONTAINS', template: "CONTAINS({0}, 'text')" },
  { label: 'STARTSWITH', template: "STARTSWITH({0}, 'pre')" },
  { label: 'ENDSWITH', template: "ENDSWITH({0}, 'suf')" },
  { label: 'STRING-LENGTH', template: 'STRINGLENGTH({0})' },
  { label: 'EQUALS (for IF/WHEN)', template: "EQUALS({0}, 'value')" },
  { label: 'IF GREATER-THAN (numeric, w/ default)', template: "IF(GT({0}, 0), {0}, '1')" },
  { label: 'IF (if / else)', template: "IF(EQUALS({0}, 'value'), 'yes', 'no')" },
  { label: 'WHEN / OTHERWISE (multi-branch)', template: "WHEN({0}, 'valueA', {1}, 'valueB', 'otherwiseValue')" },
  { label: 'AND (all true)', template: "AND(EXISTS({0}), EQUALS({1}, 'value'))" },
  { label: 'OR (any true)', template: "OR(EQUALS({0}, 'A'), EQUALS({0}, 'B'))" },
  { label: 'NOT', template: "NOT(EQUALS({0}, 'value'))" },
  { label: 'EXISTS (non-empty)', template: 'EXISTS({0})' },
  { label: 'ISEMPTY', template: 'ISEMPTY({0})' },
  { label: 'CURRENT DATE-TIME (timezone)', template: "CURRENTDATETIME('Asia/Singapore')",
    title: 'XSLT 1.0 uses EXSLT date:date-time() (server timezone)' },
  { label: 'Clear (direct copy)', template: '' },
];

@Component({
  selector: 'app-function-menu',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './function-menu.component.html',
})
export class FunctionMenuComponent {
  @Input() open = false;
  @Output() openChange = new EventEmitter<boolean>();
  @Output() pick = new EventEmitter<string>();

  builtins = BUILTIN_FUNCTIONS;

  constructor(public workspace: WorkspaceService) {}

  toggle(): void {
    this.openChange.emit(!this.open);
  }

  choose(template: string): void {
    this.pick.emit(template);
    this.openChange.emit(false);
  }

  jarTemplate(paramCount: number): string {
    return Array.from({ length: Math.max(paramCount, 1) }, (_, i) => `{${i}}`).join(', ');
  }
}

import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

/** CSV: which line holds the column names. Auto-detect (null), a row number, or no header row (0).
 * The first lines of the input are listed with their numbers; clicking one makes it the header. */
@Component({
  selector: 'app-csv-header-picker',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="csv-hdr">
      <div class="csv-hdr-bar">
        <span class="csv-hdr-label">Header row</span>
        <select [ngModel]="mode()" (ngModelChange)="setMode($event)" style="width: auto;">
          <option value="auto">Auto-detect</option>
          <option value="row">Row number</option>
          <option value="none">No header row</option>
        </select>
        <input *ngIf="mode() === 'row'" type="number" min="1" [max]="total || null" class="csv-hdr-num"
               [ngModel]="value" (ngModelChange)="setRow($event)" title="Line number of the column names (1 = first line)">
        <span class="muted" *ngIf="mode() === 'auto' && detected">→ row {{ detected }}</span>
        <span class="muted" *ngIf="mode() === 'none'">columns are named column1, column2 …</span>
      </div>
      <div class="csv-preview" *ngIf="lines.length">
        <div *ngFor="let l of lines" class="csv-line" [class.hdr]="l.n === effective" [class.data]="effective !== null && l.n > effective && !!l.text.trim()"
             [class.skip]="effective !== null && effective > 0 && l.n < effective" (click)="setRow(l.n)"
             [title]="l.text.trim() ? 'Use line ' + l.n + ' as the header row' : 'Empty line'">
          <span class="ln">{{ l.n }}</span><span class="txt">{{ l.text || ' ' }}</span>
          <span class="tag" *ngIf="l.n === effective">header</span>
        </div>
        <div class="csv-more muted" *ngIf="total > lines.length">… {{ total - lines.length }} more line(s)</div>
      </div>
      <div class="hint" style="margin: 0;" *ngIf="lines.length">Click a line to use it as the column names; the rows below it are data.</div>
    </div>
  `,
})
export class CsvHeaderPickerComponent {
  /** The CSV text being edited / loaded. */
  @Input() set text(t: string | null | undefined) {
    const all = (t ?? '').replace(/^﻿/, '').split(/\r?\n/);
    while (all.length && !all[all.length - 1].trim()) all.pop();
    this.total = all.length;
    this.lines = all.slice(0, 12).map((text, i) => ({ n: i + 1, text }));
  }
  /** null / undefined = auto-detect, 0 = no header row, n = line n. */
  @Input() value: number | null | undefined = null;
  /** The line the last parse used when auto-detecting. */
  @Input() detected: number | null | undefined = null;
  @Output() valueChange = new EventEmitter<number | null>();

  lines: { n: number; text: string }[] = [];
  total = 0;

  mode(): 'auto' | 'row' | 'none' {
    return this.value == null ? 'auto' : this.value === 0 ? 'none' : 'row';
  }

  get effective(): number | null {
    return this.value == null ? (this.detected ?? null) : this.value;
  }

  setMode(m: 'auto' | 'row' | 'none'): void {
    this.valueChange.emit(m === 'auto' ? null : m === 'none' ? 0 : (this.effective || 1));
  }

  setRow(n: number | string): void {
    const v = Math.floor(Number(n));
    if (!v || v < 1) return;
    const line = this.lines.find((l) => l.n === v);
    if (line && !line.text.trim()) return;
    this.valueChange.emit(v);
  }
}

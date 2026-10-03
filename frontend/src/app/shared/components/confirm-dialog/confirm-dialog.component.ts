import { CommonModule } from '@angular/common';
import { Component, HostListener, Injectable, signal } from '@angular/core';

interface ConfirmRequest {
  title: string;
  message: string;
  yes: string;
  resolve: (ok: boolean) => void;
}

/** App-wide Yes / No confirmation: `if (await confirm.ask('Delete X?')) …` */
@Injectable({ providedIn: 'root' })
export class ConfirmService {
  readonly pending = signal<ConfirmRequest | null>(null);

  ask(message: string, title = 'Please confirm', yes = 'Yes, delete'): Promise<boolean> {
    this.pending()?.resolve(false);
    return new Promise((resolve) => this.pending.set({ title, message, yes, resolve }));
  }

  answer(ok: boolean): void {
    const p = this.pending();
    this.pending.set(null);
    p?.resolve(ok);
  }
}

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="modal-backdrop" *ngIf="confirm.pending() as p" (click)="confirm.answer(false)" style="z-index: 400;">
      <div class="modal" style="width: 400px;" (click)="$event.stopPropagation()" role="alertdialog" aria-modal="true">
        <h2>{{ p.title }}</h2>
        <div style="font-size: 12.5px; line-height: 1.5; white-space: pre-line; margin-top: 6px;">{{ p.message }}</div>
        <div class="modal-actions">
          <button class="ghost" (click)="confirm.answer(false)">No</button>
          <button class="danger" (click)="confirm.answer(true)" autofocus>{{ p.yes }}</button>
        </div>
      </div>
    </div>
  `,
})
export class ConfirmDialogComponent {
  constructor(public confirm: ConfirmService) {}

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.confirm.pending()) this.confirm.answer(false);
  }
}

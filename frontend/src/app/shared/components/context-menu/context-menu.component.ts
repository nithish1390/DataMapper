import { CommonModule } from '@angular/common';
import { Component, HostListener, Injectable, signal } from '@angular/core';

export interface MenuItem {
  label?: string;
  action?: () => void;
  disabled?: boolean;
  separator?: boolean;
  children?: MenuItem[];
  hint?: string;
}

/** Opens one right-click menu at a time, anywhere in the app. */
@Injectable({ providedIn: 'root' })
export class ContextMenuService {
  readonly state = signal<{ x: number; y: number; items: MenuItem[] } | null>(null);

  open(event: MouseEvent, items: MenuItem[]): void {
    event.preventDefault();
    event.stopPropagation();
    this.state.set({ x: event.clientX, y: event.clientY, items });
  }

  close(): void {
    this.state.set(null);
  }
}

@Component({
  selector: 'app-context-menu',
  standalone: true,
  imports: [CommonModule],
  template: `
    <ng-container *ngIf="menu.state() as s">
      <div class="ctx-menu" [style.left.px]="clampX(s.x)" [style.top.px]="clampY(s.y, s.items.length)"
           (click)="$event.stopPropagation()" (contextmenu)="$event.preventDefault()">
        <ng-container *ngTemplateOutlet="list; context: { $implicit: s.items }"></ng-container>
      </div>
    </ng-container>

    <ng-template #list let-items>
      <ng-container *ngFor="let it of items">
        <div *ngIf="it.separator" class="ctx-sep"></div>
        <div *ngIf="!it.separator" class="ctx-item" [class.disabled]="it.disabled" [class.has-sub]="it.children?.length"
             (click)="run(it)">
          <span>{{ it.label }}</span>
          <span class="ctx-hint" *ngIf="it.hint">{{ it.hint }}</span>
          <span class="ctx-arrow" *ngIf="it.children?.length">▸</span>
          <div class="ctx-menu ctx-sub" *ngIf="it.children?.length">
            <ng-container *ngTemplateOutlet="list; context: { $implicit: it.children }"></ng-container>
          </div>
        </div>
      </ng-container>
    </ng-template>
  `,
})
export class ContextMenuComponent {
  constructor(public menu: ContextMenuService) {}

  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  @HostListener('window:blur')
  close(): void {
    this.menu.close();
  }

  run(it: MenuItem): void {
    if (it.disabled || it.children?.length || !it.action) return;
    this.menu.close();
    it.action();
  }

  clampX(x: number): number {
    return Math.min(x, window.innerWidth - 240);
  }

  clampY(y: number, n: number): number {
    return Math.max(4, Math.min(y, window.innerHeight - n * 27 - 12));
  }
}

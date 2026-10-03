import { Injectable, signal } from '@angular/core';

export interface ToastState {
  message: string;
  isError: boolean;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly current = signal<ToastState | null>(null);
  private timer?: ReturnType<typeof setTimeout>;

  show(message: string, isError = false): void {
    clearTimeout(this.timer);
    this.current.set({ message, isError });
    this.timer = setTimeout(() => this.current.set(null), 4200);
  }
}

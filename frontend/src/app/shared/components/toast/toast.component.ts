import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'app-toast',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="toast" *ngIf="toast.current() as t" [class.err]="t.isError">{{ t.message }}</div>
  `,
})
export class ToastComponent {
  constructor(public toast: ToastService) {}
}

import { Component } from '@angular/core';
import { MapperPageComponent } from './features/mapper/components/mapper-page/mapper-page.component';
import { ToastComponent } from './shared/components/toast/toast.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [MapperPageComponent, ToastComponent],
  template: `
    <app-mapper-page></app-mapper-page>
    <app-toast></app-toast>
  `,
})
export class AppComponent {}

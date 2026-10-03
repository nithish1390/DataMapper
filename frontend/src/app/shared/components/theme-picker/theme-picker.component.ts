import { CommonModule } from '@angular/common';
import { Component, HostListener, Injectable, signal } from '@angular/core';

export type ThemeMode = 'system' | 'light' | 'dark';
export type Density = 'compact' | 'comfortable';

export interface Palette {
  id: string;
  name: string;
  accent: string;
  wire: string;
  wireAi: string;
}

/** Colour palettes: accent (buttons, selection), wire (value mapping lines), wire-ai (conditions). */
export interface CustomColors {
  accent: string;
  wire: string;
  wireAi: string;
  formula: string;
}

export const DEFAULT_CUSTOM: CustomColors = { accent: '#3B4E8A', wire: '#0E7C86', wireAi: '#C77D2E', formula: '' };

export const PALETTES: Palette[] = [
  { id: 'indigo', name: 'Indigo', accent: '#3B4E8A', wire: '#0E7C86', wireAi: '#C77D2E' },
  { id: 'ocean', name: 'Ocean', accent: '#0B6E99', wire: '#0E9F8E', wireAi: '#D9822B' },
  { id: 'forest', name: 'Forest', accent: '#2F6B45', wire: '#2C7DA0', wireAi: '#B5651D' },
  { id: 'sunset', name: 'Sunset', accent: '#B54A2C', wire: '#6B4FA0', wireAi: '#C9921A' },
  { id: 'plum', name: 'Plum', accent: '#7A3E8E', wire: '#2A8C82', wireAi: '#C0563C' },
  { id: 'graphite', name: 'Graphite', accent: '#44505F', wire: '#3A7CA5', wireAi: '#B07D2B' },
  { id: 'classic', name: 'Classic Blue', accent: '#1F5AA6', wire: '#4A8C2A', wireAi: '#8A6CC7' },
];

const KEY = 'mapsheet-ai.theme';
const OLD_KEY = 'datamapper.theme';  // saved before the rename

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>('system');
  readonly palette = signal<string>('indigo');
  readonly density = signal<Density>('compact');
  readonly custom = signal<CustomColors>({ ...DEFAULT_CUSTOM });

  constructor() {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) ?? localStorage.getItem(OLD_KEY) ?? '{}');
      if (saved.mode) this.mode.set(saved.mode);
      const pal = saved.palette;  // unknown / old ids fall back to the default palette
      if (pal && (pal === 'custom' || PALETTES.some((p) => p.id === pal))) this.palette.set(pal);
      if (saved.custom) this.custom.set({ ...DEFAULT_CUSTOM, ...saved.custom });
      if (saved.density) this.density.set(saved.density);
    } catch {
      /* storage unavailable: defaults */
    }
    this.apply();
  }

  set(patch: { mode?: ThemeMode; palette?: string; density?: Density; custom?: Partial<CustomColors> }): void {
    if (patch.custom) this.custom.set({ ...this.custom(), ...patch.custom });
    if (patch.mode) this.mode.set(patch.mode);
    if (patch.palette) this.palette.set(patch.palette);
    if (patch.density) this.density.set(patch.density);
    this.apply();
    try {
      localStorage.setItem(KEY, JSON.stringify({
        mode: this.mode(), palette: this.palette(), density: this.density(), custom: this.custom(),
      }));
    } catch {
      /* ignore */
    }
  }

  private apply(): void {
    const root = document.documentElement;
    if (this.mode() === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', this.mode());
    root.setAttribute('data-palette', this.palette());
    root.setAttribute('data-density', this.density());
    const c = this.custom();
    root.style.setProperty('--custom-accent', c.accent);
    root.style.setProperty('--custom-wire', c.wire);
    root.style.setProperty('--custom-wire-ai', c.wireAi);
    if (c.formula) {
      root.style.setProperty('--custom-formula', c.formula);
      root.setAttribute('data-custom-formula', '');
    } else {
      root.style.removeProperty('--custom-formula');
      root.removeAttribute('data-custom-formula');
    }
  }
}

@Component({
  selector: 'app-theme-picker',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div style="position: relative;">
      <button class="ghost" (click)="open.set(!open()); $event.stopPropagation()" title="Colour theme">🎨 Theme</button>
      <div *ngIf="open()" class="theme-pop" (click)="$event.stopPropagation()">
        <div class="theme-sec">Mode</div>
        <div class="tabbtns">
          <button *ngFor="let m of modes" [class.active]="theme.mode() === m.id" (click)="theme.set({ mode: m.id })">{{ m.label }}</button>
        </div>
        <div class="theme-sec">Colours</div>
        <div class="theme-swatches">
          <button *ngFor="let p of palettes" class="swatch" [class.on]="theme.palette() === p.id"
                  (click)="theme.set({ palette: p.id })" [title]="p.name">
            <span class="sw-dots">
              <i [style.background]="p.accent"></i><i [style.background]="p.wire"></i><i [style.background]="p.wireAi"></i>
            </span>
            <span class="sw-name">{{ p.name }}</span>
          </button>
          <button class="swatch" [class.on]="theme.palette() === 'custom'" (click)="theme.set({ palette: 'custom' })" title="Your own colours">
            <span class="sw-dots">
              <i [style.background]="theme.custom().accent"></i><i [style.background]="theme.custom().wire"></i><i [style.background]="theme.custom().wireAi"></i>
            </span>
            <span class="sw-name">Custom…</span>
          </button>
        </div>
        <div class="custom-colors" *ngIf="theme.palette() === 'custom'">
          <span>Accent (buttons, selection)</span>
          <input type="color" [value]="theme.custom().accent" (input)="theme.set({ custom: { accent: $any($event.target).value } })">
          <span>Mapping lines</span>
          <input type="color" [value]="theme.custom().wire" (input)="theme.set({ custom: { wire: $any($event.target).value } })">
          <span>Condition lines / statements</span>
          <input type="color" [value]="theme.custom().wireAi" (input)="theme.set({ custom: { wireAi: $any($event.target).value } })">
          <span>Formula cells <a href="" *ngIf="theme.custom().formula" (click)="$event.preventDefault(); theme.set({ custom: { formula: '' } })">reset</a></span>
          <input type="color" [value]="theme.custom().formula || '#fffbe8'" (input)="theme.set({ custom: { formula: $any($event.target).value } })">
        </div>
        <div class="theme-sec">Density</div>
        <div class="tabbtns">
          <button [class.active]="theme.density() === 'compact'" (click)="theme.set({ density: 'compact' })">Compact</button>
          <button [class.active]="theme.density() === 'comfortable'" (click)="theme.set({ density: 'comfortable' })">Comfortable</button>
        </div>
      </div>
    </div>
  `,
})
export class ThemePickerComponent {
  open = signal(false);
  palettes = PALETTES;
  modes: { id: ThemeMode; label: string }[] = [
    { id: 'system', label: 'System' }, { id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' },
  ];

  constructor(public theme: ThemeService) {}

  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  close(): void {
    this.open.set(false);
  }
}

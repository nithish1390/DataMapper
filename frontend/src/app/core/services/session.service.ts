import { Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { SessionFile, WorkspaceService } from './workspace.service';

const DB = 'mapsheet-ai';
const OLD_DB = 'datamapper';  // auto-saves made before the rename
const STORE = 'sessions';
const DRAFT_KEY = 'autosave';

/** Tiny IndexedDB key/value helper (sessions can be several MB — too big for localStorage). */
function idb<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest, db = DB): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    let open: IDBOpenDBRequest;
    try {
      open = indexedDB.open(db, 1);
    } catch (e) {
      reject(e);
      return;
    }
    open.onupgradeneeded = () => open.result.createObjectStore(STORE);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction(STORE, mode);
      const req = run(tx.objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => reject(req.error);
      tx.oncomplete = () => open.result.close();
    };
  });
}

/** Sessions: save / open .mapsheet.json files, plus an automatic draft in this browser
 * (written a few seconds after each change and when the page is closed or reloaded). */
@Injectable({ providedIn: 'root' })
export class SessionService {
  readonly draftInfo = signal<{ name: string; saved_at: string } | null>(null);
  readonly lastFileSave = signal<string | null>(null);
  /** Run before every save (e.g. the Mapping Builder applies a pending draft). */
  readonly beforeSave: (() => void)[] = [];
  private timer?: ReturnType<typeof setTimeout>;

  constructor(private workspace: WorkspaceService, private api: ApiService) {
    this.loadDraftInfo();
  }

  fileName(): string {
    const slug = this.workspace.sessionName().trim().replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'session';
    return `${slug}.mapsheet.json`;
  }

  /** Downloads the current session as <name>.mapsheet.json. */
  saveToFile(includeSecrets = false): void {
    this.beforeSave.forEach((fn) => fn());
    const data = this.workspace.exportSession(includeSecrets);
    const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = this.fileName();
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    this.workspace.markSaved();
    this.lastFileSave.set(new Date().toISOString());
    void this.saveDraft();
  }

  async openFile(file: File): Promise<string> {
    const text = await file.text();
    let data: SessionFile;
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(`${file.name} is not valid JSON.`);
    }
    await this.load(data);
    this.workspace.markSaved();
    return data.name;
  }

  /** Imports a session, then re-parses its schemas with the current parser, so trees saved by an
   * older version gain newer details (XML attributes, choice markers, types). Mappings are kept. */
  async load(data: SessionFile): Promise<void> {
    this.workspace.importSession(data);
    await this.refreshSchemas();
  }

  async refreshSchemas(): Promise<void> {
    for (const src of this.workspace.sources()) {
      if (!src.ready || !src.raw?.trim()) continue;
      try {
        const res = await firstValueFrom(this.api.parse(src.type, src.raw));
        this.workspace.patchSource(src.id, { fields: res.tree, namespace: res.namespace ?? src.namespace ?? null });
      } catch {
        /* keep the saved tree */
      }
    }
    const t = this.workspace.target();
    if (t.ready && t.raw?.trim()) {
      try {
        const res = await firstValueFrom(this.api.parse(t.type, t.raw));
        this.workspace.patchTarget({ fields: res.tree, namespace: res.namespace ?? t.namespace ?? null });
      } catch {
        /* keep the saved tree */
      }
    }
    this.workspace.bumpLayout();
  }

  // ---------------------------------------------------------- browser draft
  /** Debounced auto-save after changes. */
  scheduleDraft(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.saveDraft(), 4000);
  }

  async saveDraft(): Promise<void> {
    if (!this.workspace.dirty()) return;
    const data = this.workspace.exportSession(false);
    try {
      await idb('readwrite', (s) => s.put(data, DRAFT_KEY));
      this.draftInfo.set({ name: data.name, saved_at: data.saved_at });
    } catch {
      /* storage unavailable (private window etc.) */
    }
  }

  async readDraft(): Promise<SessionFile | undefined> {
    try {
      return (await idb<SessionFile>('readonly', (s) => s.get(DRAFT_KEY)))
        ?? (await idb<SessionFile>('readonly', (s) => s.get(DRAFT_KEY), OLD_DB));
    } catch {
      return undefined;
    }
  }

  async restoreDraft(): Promise<boolean> {
    const draft = await this.readDraft();
    if (!draft) return false;
    await this.load(draft);
    return true;
  }

  async discardDraft(): Promise<void> {
    try {
      await idb('readwrite', (s) => s.delete(DRAFT_KEY));
      await idb('readwrite', (s) => s.delete(DRAFT_KEY), OLD_DB);
    } catch {
      /* ignore */
    }
    this.draftInfo.set(null);
  }

  private async loadDraftInfo(): Promise<void> {
    const d = await this.readDraft();
    this.draftInfo.set(d ? { name: d.name, saved_at: d.saved_at } : null);
  }
}

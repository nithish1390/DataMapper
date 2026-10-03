import { Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';

export interface InputFile {
  text: string;
  /** Excel workbook: its sheets, and the one converted to CSV. */
  sheets: string[];
  sheet: string | null;
  spreadsheet: boolean;
}

/** Reads an uploaded source / target file. Excel workbooks (.xlsx / .xls) are converted to CSV text
 * on the backend; other binary files are rejected instead of being shown as garbage. */
@Injectable({ providedIn: 'root' })
export class InputFileService {
  constructor(private api: ApiService) {}

  async read(file: File, sheet?: string | null): Promise<InputFile> {
    const head = new Uint8Array(await file.slice(0, 4096).arrayBuffer());
    const zip = head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04;
    const ole = head[0] === 0xd0 && head[1] === 0xcf && head[2] === 0x11 && head[3] === 0xe0;
    if (zip || ole || /\.(xlsx|xlsm|xls)$/i.test(file.name)) {
      const res = await firstValueFrom(this.api.previewSheet(file, sheet ?? undefined)).catch((err) => {
        throw new Error(err.error?.detail ?? err.message ?? 'Could not read the workbook.');
      });
      const chosen = sheet && res.sheet_names.includes(sheet) ? sheet : res.sheet_names[0] ?? null;
      return { text: toCsv(res.rows), sheets: res.sheet_names, sheet: chosen, spreadsheet: true };
    }
    if (head.includes(0)) {
      throw new Error(`"${file.name}" is a binary file, not text. Upload a text file (XSD, XML, JSON, CSV, SWIFT, .java) or an Excel workbook.`);
    }
    return { text: await file.text(), sheets: [], sheet: null, spreadsheet: false };
  }
}

/** Rows -> CSV text (comma separated; cells with , " or line breaks quoted). */
export function toCsv(rows: string[][]): string {
  // drop trailing empty cells so short rows don't end in ",,,"
  return rows.map((r) => {
    const cells = [...r];
    while (cells.length > 1 && !String(cells[cells.length - 1] ?? '').trim()) cells.pop();
    return cells.map((c) => {
      const v = String(c ?? '');
      return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    }).join(',');
  }).join('\n');
}

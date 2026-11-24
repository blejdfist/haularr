import { fmtSize as size, type IconKind } from './status';

/** One row in a stage's file list. Every stage maps its own data onto this shape. */
export type Row = { key: string; path: string; kind: IconKind; meta?: string; note?: string; tone?: 'error' | 'warn'; pct?: number };
export type List = { caption: string[]; rows: Row[]; empty?: string };

const FILE_ICON: Record<string, IconKind> = {
  pending: 'pending',
  in_progress: 'running',
  completed: 'done',
  verified: 'done',
  failed: 'failed',
};
const VERIFY_ICON: Record<string, IconKind> = {
  checking: 'running',
  'crc32 ok': 'done',
  'size ok': 'done',
  failed: 'failed',
  missing: 'failed',
};

export const basename = (f: string) => f.slice(f.lastIndexOf('/') + 1);

/** A file's error repeats its path first; the row already shows the path. */
export function unprefix(detail: string, path: string): string {
  const head = [path, basename(path)].find((p) => detail.startsWith(`${p}: `));
  return head ? detail.slice(head.length + 2) : detail;
}

function sizeRow(key: string, path: string, kind: IconKind, total: number, done: number, live: boolean): Row {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return { key, path, kind, meta: live ? `${pct}% · ${size(done)} / ${size(total)}` : size(total), pct: live ? pct : undefined };
}

/**
 * The list under a stage: what it worked on, file by file. Null when it has none.
 * `r` is the stage's current run; `files` the job's transfer files.
 */
export function stageList(st: string, r: any, files: any[]): List | null {
  const p = r?.progress;
  if (st === 'source_download' || st === 'transfer') {
    const live = r?.status === 'running';
    const rows: Row[] =
      st === 'transfer'
        ? files.map((f) => ({
            ...sizeRow(f.id, f.remote_relpath, FILE_ICON[f.transfer_status] ?? 'pending', f.size_bytes ?? 0, f.bytes_received ?? 0, f.transfer_status === 'in_progress'),
            ...(f.transfer_status === 'failed' && { note: 'Transfer failed', tone: 'error' as const }),
          }))
        : ((p?.files ?? []) as any[]).map((f) => {
            const finished = f.done_bytes >= f.size_bytes;
            return sizeRow(f.path, f.path, finished ? 'done' : live ? 'running' : 'pending', f.size_bytes, f.done_bytes, live && !finished);
          });
    const total = st === 'transfer' ? files.reduce((n, f) => n + (f.size_bytes ?? 0), 0) : ((p?.files ?? []) as any[]).reduce((n, f) => n + f.size_bytes, 0);
    return {
      // While running, the stage bar above already shows the total.
      caption: rows.length ? [live ? `${rows.length} files` : `${rows.length} files · ${size(total)}`] : [],
      rows,
      empty: st === 'transfer' ? 'Files are listed once the transfer starts.' : 'Files are listed once the seedbox reports them.',
    };
  }
  if (st === 'verify' && p?.files?.length)
    return {
      caption: [],
      rows: p.files.map((f: any) => {
        const bad = f.result === 'failed' || f.result === 'missing';
        return { key: f.path, path: f.path, kind: VERIFY_ICON[f.result] ?? 'pending', meta: bad ? undefined : f.detail || f.result, ...(bad && { note: unprefix(f.detail || f.result, f.path), tone: 'error' }) };
      }),
    };
  if (st === 'extract' && p?.archives?.length)
    return {
      caption: [],
      rows: p.archives.map((a: any) => ({
        key: a.archive,
        path: a.archive,
        kind: a.files ? 'done' : r.status === 'running' ? 'running' : 'failed',
        meta: a.files ? `${a.files.length} out` : undefined,
        note: a.files?.map(basename).join(', '),
      })),
    };
  if (st === 'move' && p?.files?.length)
    return { caption: [`To ${p.published_path}`], rows: p.files.map((f: string) => ({ key: f, path: f, kind: 'done' })) };
  if (st === 'inspect_import' && Array.isArray(p?.candidates))
    return {
      caption: [],
      rows: p.candidates.map((c: any) => ({
        key: c.path,
        path: basename(c.path),
        kind: c.rejection_reasons?.length ? 'warning' : 'done',
        meta: c.quality || undefined,
        ...(c.rejection_reasons?.length && { note: c.rejection_reasons.join('; '), tone: 'warn' }),
      })),
    };
  if (st === 'import' && p)
    return {
      caption: [
        p.pending && 'Library still importing',
        p.rejected?.length && `${p.rejected.length} rejected by the library, left in place`,
        p.skipped?.length && `${p.skipped.length} skipped`,
      ].filter(Boolean),
      rows: (p.imported ?? []).map((f: string) => ({ key: f, path: f, kind: 'done' })),
    };
  if (st === 'cleanup' && p)
    return {
      caption: [
        p.cleaned_a && `In progress: deleted ${p.deleted_a?.count ?? 0} files · ${size(p.deleted_a?.bytes ?? 0)}`,
        p.cleaned_b && `Completed: deleted ${p.deleted_b?.files?.length ?? 0} files the library left · ${size(p.deleted_b?.bytes ?? 0)}`,
        !p.cleaned_b && p.skipped_b && 'Completed folder kept: no library',
      ].filter(Boolean),
      rows: p.cleaned_b ? (p.deleted_b?.files ?? []).map((f: string) => ({ key: f, path: f, kind: 'done' })) : [],
    };
  return null;
}

/** Release folder shared by every file (with its trailing slash), shown once above the list. '' when none. */
export function commonRoot(paths: string[]): string {
  const first = paths[0] ?? '';
  const top = first.includes('/') ? first.slice(0, first.indexOf('/') + 1) : '';
  return top && paths.every((x) => x.startsWith(top)) ? top : '';
}

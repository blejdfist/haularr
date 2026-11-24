import { describe, it, expect } from 'vitest';
import { stageList, commonRoot, unprefix } from '../src/lib/stages';

describe('stageList', () => {
  it('transfer: one row per job file, live ones metered, failed ones noted', () => {
    const files = [
      { id: 'a', remote_relpath: 'Rel/a.r00', size_bytes: 100, bytes_received: 100, transfer_status: 'completed' },
      { id: 'b', remote_relpath: 'Rel/a.r01', size_bytes: 100, bytes_received: 40, transfer_status: 'in_progress' },
      { id: 'c', remote_relpath: 'Rel/a.rar', size_bytes: 100, bytes_received: 0, transfer_status: 'failed' },
    ];
    const list = stageList('transfer', { status: 'running' }, files)!;
    expect(list.caption).toEqual(['3 files']);
    expect(list.rows.map((r) => r.kind)).toEqual(['done', 'running', 'failed']);
    expect(list.rows[1].pct).toBe(40);
    expect(list.rows[0].pct).toBeUndefined();
    expect(list.rows[2]).toMatchObject({ note: 'Transfer failed', tone: 'error' });
  });

  it('transfer finished: caption carries the total size', () => {
    const files = [{ id: 'a', remote_relpath: 'a.mkv', size_bytes: 2048, bytes_received: 2048, transfer_status: 'completed' }];
    expect(stageList('transfer', { status: 'completed' }, files)!.caption).toEqual(['1 files · 2 KB']);
  });

  it('transfer with no files yet: empty message', () => {
    const list = stageList('transfer', undefined, [])!;
    expect(list.rows).toEqual([]);
    expect(list.empty).toMatch(/transfer starts/);
  });

  it('verify: a bad file is an error row without the repeated filename', () => {
    const r = {
      progress: {
        files: [
          { path: 'Rel/a.r00', result: 'crc32 ok' },
          { path: 'Rel/a.rar', result: 'failed', detail: 'a.rar: CRC mismatch' },
        ],
      },
    };
    const rows = stageList('verify', r, [])!.rows;
    expect(rows[0]).toMatchObject({ kind: 'done', meta: 'crc32 ok' });
    expect(rows[1]).toMatchObject({ kind: 'failed', note: 'CRC mismatch', tone: 'error', meta: undefined });
  });

  it('import: caption lists what the library left, rows what it took', () => {
    const r = { progress: { imported: ['x.mkv'], rejected: ['y.mkv'], skipped: [] } };
    const list = stageList('import', r, [])!;
    expect(list.caption).toEqual(['1 rejected by the library, left in place']);
    expect(list.rows).toEqual([{ key: 'x.mkv', path: 'x.mkv', kind: 'done' }]);
  });

  it('stages without a list return null', () => {
    expect(stageList('check_library', { progress: {} }, [])).toBeNull();
    expect(stageList('verify', { progress: { files: [] } }, [])).toBeNull();
  });
});

describe('commonRoot', () => {
  it('is the shared top folder with its slash', () => {
    expect(commonRoot(['Rel/a', 'Rel/sub/b'])).toBe('Rel/');
  });
  it('is empty when files differ or sit at the top', () => {
    expect(commonRoot(['A/a', 'B/b'])).toBe('');
    expect(commonRoot(['a.mkv'])).toBe('');
    expect(commonRoot([])).toBe('');
  });
});

describe('unprefix', () => {
  it('drops the full path or the basename in front of the detail', () => {
    expect(unprefix('Rel/a.rar: bad', 'Rel/a.rar')).toBe('bad');
    expect(unprefix('a.rar: bad', 'Rel/a.rar')).toBe('bad');
    expect(unprefix('bad', 'Rel/a.rar')).toBe('bad');
  });
});

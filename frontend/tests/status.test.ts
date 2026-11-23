import { describe, it, expect } from 'vitest';
import { STATUS_GROUPS, groupOf, badgeColor, sourceHealth, statusLabel } from '../src/lib/status';

const ALL = [
  'queued', 'running', 'waiting_source', 'waiting_external', 'retry_wait', 'paused',
  'needs_attention', 'failed', 'completed', 'completed_with_warnings', 'cancelled', 'skipped',
];

describe('status', () => {
  it('groups statuses', () => {
    expect(groupOf('retry_wait')).toBe('active');
    expect(groupOf('needs_attention')).toBe('failed');
    expect(groupOf('cancelled')).toBe('done');
    expect(groupOf('bogus')).toBeNull();
  });
  it('maps every JobStatus to exactly one group', () => {
    for (const s of ALL) {
      const n = Object.values(STATUS_GROUPS).filter((g) => g.includes(s)).length;
      expect(n, s).toBe(1);
    }
    expect(Object.values(STATUS_GROUPS).flat().length).toBe(ALL.length);
  });
  it('badge colors', () => {
    expect(badgeColor('failed')).toBe('red');
    expect(badgeColor('needs_attention')).toBe('red');
    expect(badgeColor('paused')).toBe('yellow');
    expect(badgeColor('running')).toBe('blue');
    expect(badgeColor('completed')).toBe('green');
    expect(badgeColor('completed_with_warnings')).toBe('yellow');
    expect(badgeColor('skipped')).toBe('gray');
    expect(badgeColor('cancelled')).toBe('gray');
    expect(badgeColor('bogus')).toBe('gray');
  });
  it('source health', () => {
    expect(sourceHealth({ last_scan_at: null, last_scan_error: null })).toBe('never');
    expect(sourceHealth({ last_scan_at: '2026-11-23T00:00:00Z', last_scan_error: 'x' })).toBe('error');
    expect(sourceHealth({ last_scan_at: '2026-11-23T00:00:00Z', last_scan_error: null })).toBe('ok');
  });
});

import { parseUtc } from '../src/lib/status';
describe('parseUtc', () => {
  it('treats naive strings as UTC', () => {
    expect(parseUtc('2026-01-01T10:00:00').toISOString()).toBe('2026-01-01T10:00:00.000Z');
  });
  it('leaves Z and offsets alone', () => {
    expect(parseUtc('2026-01-01T10:00:00Z').toISOString()).toBe('2026-01-01T10:00:00.000Z');
    expect(parseUtc('2026-01-01T10:00:00+02:00').toISOString()).toBe('2026-01-01T08:00:00.000Z');
  });
});

describe('statusLabel', () => {
  it('explains jobs waiting for a fetch config', () => {
    expect(statusLabel({ status: 'waiting_source', error_code: 'no_transfer_config' })).toBe('Waiting for fetch config');
  });
  it('falls back to the raw status', () => {
    expect(statusLabel({ status: 'running' })).toBe('running');
  });
});

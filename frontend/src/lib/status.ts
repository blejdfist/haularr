export type StatusGroup = 'active' | 'failed' | 'done';

export const STATUS_GROUPS: Record<StatusGroup, string[]> = {
  active: ['queued', 'running', 'retry_wait', 'waiting_source', 'waiting_external', 'paused'],
  failed: ['failed', 'needs_attention'],
  done: ['completed', 'completed_with_warnings', 'skipped', 'cancelled'],
};

export function groupOf(status: string): StatusGroup | null {
  for (const g of Object.keys(STATUS_GROUPS) as StatusGroup[]) {
    if (STATUS_GROUPS[g].includes(status)) return g;
  }
  return null;
}

export function badgeColor(status: string): 'blue' | 'red' | 'green' | 'yellow' | 'gray' {
  if (status === 'paused' || status === 'completed_with_warnings') return 'yellow';
  if (status === 'completed') return 'green';
  const g = groupOf(status);
  return g === 'active' ? 'blue' : g === 'failed' ? 'red' : 'gray';
}

export type Health = 'ok' | 'error' | 'never';
/** Status dot on source/library cards: a health or a check still in flight. */
export type Dot = Health | 'checking';

export function sourceHealth(s: { last_scan_at: string | null; last_scan_error: string | null }): Health {
  if (s.last_scan_error) return 'error';
  return s.last_scan_at ? 'ok' : 'never';
}

/** Backend emits naive ISO strings that are UTC; treat them as such. */
export function parseUtc(s: string): Date {
  return new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(s) ? s : s + 'Z');
}

export function ago(s: string | null): string {
  if (!s) return '';
  const sec = Math.max(0, (Date.now() - parseUtc(s).getTime()) / 1000);
  if (sec < 60) return 'just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export type IconKind = 'running' | 'queued' | 'pending' | 'done' | 'failed' | 'warning' | 'skipped';

/** Row icon for a job; `blocked` = the job has a reason it is stuck (shown as a warning). */
export function jobIcon(status: string, blocked = false): IconKind {
  if (status === 'running') return 'running';
  if (status === 'completed') return 'done';
  if (status === 'failed' || status === 'needs_attention') return 'failed';
  if (status === 'completed_with_warnings') return 'warning';
  if (status === 'cancelled' || status === 'skipped') return 'skipped';
  return blocked ? 'warning' : 'queued';
}

/** Icon for one stage run (undefined = not started). */
export function runIcon(status: string | undefined): IconKind {
  if (!status) return 'pending';
  if (status === 'running') return 'running';
  if (status === 'succeeded') return 'done';
  if (status === 'failed' || status === 'needs_attention') return 'failed';
  if (status === 'skipped') return 'skipped';
  return 'queued';
}

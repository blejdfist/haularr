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

export function sourceHealth(s: { last_scan_at: string | null; last_scan_error: string | null }): Health {
  if (s.last_scan_error) return 'error';
  return s.last_scan_at ? 'ok' : 'never';
}

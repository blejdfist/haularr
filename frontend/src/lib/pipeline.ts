import type { Step, StepState } from '$lib/components/steps/types';

/** Backend job stages grouped into the phases shown to the user. */
export const PHASES = [
  { key: 'fetch', label: 'Fetch', stages: ['resolve_source', 'download'] },
  { key: 'check', label: 'Check', stages: ['verify'] },
  { key: 'unpack', label: 'Unpack', stages: ['extract', 'publish'] },
  { key: 'import', label: 'Import', stages: ['inspect_import', 'import', 'confirm_import'] },
  { key: 'finish', label: 'Finish', stages: ['notify', 'cleanup'] },
];

const STATE: Record<string, StepState> = {
  running: 'active',
  queued: 'active',
  waiting_source: 'waiting',
  waiting_external: 'waiting',
  retry_wait: 'waiting',
  paused: 'waiting',
  failed: 'failed',
  needs_attention: 'failed',
  cancelled: 'failed',
};

type JobLike = { status: string; stage: string; error_code?: string | null; error_detail?: string | null };

export function reasonFor(job: JobLike): string | undefined {
  if (job.status === 'cancelled') return 'Cancelled';
  if (job.status === 'paused') return 'Paused';
  if (job.error_detail) return job.error_detail;
  if (job.error_code === 'no_transfer_config') return 'No fetch config on this source';
  return undefined;
}

export function jobSteps(job: JobLike, progress?: number): Step[] {
  const state = STATE[job.status];
  const cur = Math.max(0, PHASES.findIndex((p) => p.stages.includes(job.stage)));
  return PHASES.map((p, i): Step => {
    const base = { key: p.key, label: p.label };
    // Unknown status (completed, skipped, ...) means the job is finished.
    if (!state || i < cur) return { ...base, state: 'done' };
    if (i > cur) return { ...base, state: 'pending' };
    // Live progress (download or extract) belongs to whichever phase is running.
    if (state === 'active') return { ...base, state, progress };
    return { ...base, state, reason: reasonFor(job) };
  });
}

type RunLike = { stage: string; started_at: string | null };

/**
 * The run that describes each stage's current state. Runs are replayed in
 * start order; a stage starting again (retry, retry-import, restart) opens a
 * new pass, so runs of the stages after it belong to the old pass and drop out.
 * Attempt numbers are useless here: restart resets them.
 */
export function currentRuns<R extends RunLike>(runs: R[]): Map<string, R> {
  const order = PHASES.flatMap((p) => p.stages);
  const latest = new Map<string, R>();
  const sorted = [...runs].sort((a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? ''));
  for (const r of sorted) {
    for (const st of order.slice(order.indexOf(r.stage) + 1)) latest.delete(st);
    latest.set(r.stage, r);
  }
  return latest;
}

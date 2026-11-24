import type { Step, StepState } from '$lib/components/steps/types';

/** Backend job stages grouped into the phases shown to the user. */
export const PHASES = [
  { key: 'download', label: 'Download', stages: ['source_download'] },
  { key: 'library', label: 'Library', stages: ['check_library'] },
  { key: 'transfer', label: 'Transfer', stages: ['transfer'] },
  { key: 'verify', label: 'Verify', stages: ['verify'] },
  { key: 'unpack', label: 'Unpack', stages: ['extract', 'move'] },
  { key: 'import', label: 'Import', stages: ['inspect_import', 'import'] },
  { key: 'finish', label: 'Finish', stages: ['cleanup'] },
];

const STATE: Record<string, StepState> = {
  running: 'active',
  queued: 'active',
  waiting_source: 'active', // downloading on the seedbox
  waiting_transfer: 'waiting',
  waiting_library: 'waiting',
  waiting_approval: 'waiting',
  waiting_external: 'waiting',
  retry_wait: 'waiting',
  paused: 'waiting',
  failed: 'failed',
  needs_attention: 'failed',
  cancelled: 'failed',
};

/** Stages that report byte progress; while active they start at 0% instead of showing no progress. */
const METERED = ['source_download', 'transfer', 'extract'];

type JobLike = { status: string; stage: string; error_code?: string | null; error_detail?: string | null };

export function reasonFor(job: JobLike): string | undefined {
  if (job.status === 'cancelled') return 'Cancelled';
  if (job.status === 'paused') return 'Paused';
  if (job.status === 'waiting_library') return 'Not in library yet';
  if (job.status === 'waiting_approval') return 'Waiting for you to start it';
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
    // Live progress (seedbox download, transfer or extract) belongs to whichever phase is running.
    if (state === 'active') return { ...base, state, progress: progress ?? (METERED.includes(job.stage) ? 0 : undefined) };
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
  // Same start time (e.g. second resolution): fall back to pipeline order.
  const sorted = [...runs].sort(
    (a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? '') || order.indexOf(a.stage) - order.indexOf(b.stage),
  );
  for (const r of sorted) {
    for (const st of order.slice(order.indexOf(r.stage) + 1)) latest.delete(st);
    latest.set(r.stage, r);
  }
  return latest;
}

export type RateSample = { got: number; t: number };

/**
 * Byte rate (per second) over the last `window` ms of samples, for ETAs.
 * Only points where the count changed are kept, and a lone starting point slides
 * forward while nothing moves, so idle time before the transfer starts (or
 * before the drawer saw it move) doesn't drag the rate down.
 */
export function trackRate(
  samples: RateSample[],
  got: number,
  t: number,
  window = 20_000,
): { samples: RateSample[]; rate?: number } {
  const last = samples.at(-1);
  let s: RateSample[];
  if (!last || got < last.got) s = [{ got, t }]; // first sample, or counter restarted
  else if (got === last.got) s = samples.length === 1 ? [{ got, t }] : samples;
  else s = [...samples, { got, t }];
  s = s.filter((x, i) => x.t >= t - window || i >= s.length - 2);
  const a = s[0];
  const b = s[s.length - 1];
  return { samples: s, rate: s.length > 1 && b.t > a.t ? (b.got - a.got) / ((b.t - a.t) / 1000) : undefined };
}

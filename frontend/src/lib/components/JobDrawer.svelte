<script lang="ts">
  import { untrack } from 'svelte';
  import { Drawer, Button, Alert } from 'flowbite-svelte';
  import { ChevronRightOutline } from 'flowbite-svelte-icons';
  import { endpoints } from '$lib/api/client';
  import { subscribe, coalesce, type JobEvent } from '$lib/live';
  import { groupOf, parseUtc, ago, runIcon, fmtSize, SPEED_STALE_MS } from '$lib/status';
  import { stageList } from '$lib/stages';
  import StatusIcon from '$lib/components/StatusIcon.svelte';
  import FileList from '$lib/components/FileList.svelte';
  import EventTimeline from '$lib/components/EventTimeline.svelte';
  import LibraryVerdict from '$lib/components/LibraryVerdict.svelte';
  import { PHASES, jobSteps, currentRuns, trackRate, type RateSample } from '$lib/pipeline';
  import StepTrack from '$lib/components/steps/StepTrack.svelte';
  import { currentIndex, type Step } from '$lib/components/steps/types';

  let { jobId, open = $bindable(false), onchanged }: {
    jobId: string | null;
    open: boolean;
    onchanged: () => void;
  } = $props();

  let job = $state<any>(null);
  let events = $state<any[]>([]);
  let error = $state('');
  let busy = $state(false);
  let selected = $state<string | undefined>();
  // Per-stage byte samples across polls: seconds left for each running stage with progress.
  let rates: Record<string, RateSample[]> = {};
  let etas = $state<Record<string, number>>({});
  let speeds = $state<Record<string, { bps: number; at: number }>>({});
  // Ticks so a speed goes stale when no new bytes arrive (local clock, no requests).
  let now = $state(Date.now());
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 2000);
    return () => clearInterval(t);
  });

  function sample(stage: string, p: { got: number; total: number } | null) {
    if (!p) return;
    const { samples, rate } = trackRate(rates[stage] ?? [], p.got, Date.now());
    rates[stage] = samples;
    if (rate) {
      etas[stage] = (p.total - p.got) / rate;
      speeds[stage] = { bps: rate, at: Date.now() };
    } else {
      delete etas[stage];
      delete speeds[stage];
    }
  }

  /** The seedbox reports its own download rate; it beats one measured from our polls. */
  function sourceRate(stage: string, p: { bps: number; bytes_done?: number; bytes_total?: number }) {
    speeds[stage] = { bps: p.bps, at: Date.now() };
    if (p.bps && p.bytes_total) etas[stage] = (p.bytes_total - (p.bytes_done ?? 0)) / p.bps;
    else delete etas[stage];
  }

  async function load(id: string) {
    error = '';
    try {
      job = await endpoints.jobs.get(id);
      events = job.events ?? [];
      for (const r of job.stage_runs ?? []) {
        if (r.status !== 'running') continue;
        if (typeof r.progress?.bps === 'number') sourceRate(r.stage, r.progress);
        else sample(r.stage, r.stage === 'transfer' ? fetched : bytes(r.progress));
      }
    } catch (e: any) {
      error = e.message;
    }
  }

  $effect(() => {
    if (open && jobId) {
      const id = jobId;
      untrack(() => {
        job = null;
        events = [];
        selected = undefined;
        rates = {};
        etas = {};
        speeds = {};
        load(id);
      });
      // Live view: refetch this job whenever the stream reports a change to it, and on
      // (re)connect in case something changed while disconnected.
      const refetch = coalesce(() => load(id));
      return subscribe('/events/jobs', {
        open: refetch,
        job: (e: JobEvent) => e.id === id && refetch(),
      });
    }
  });

  async function act(fn: (id: string) => Promise<any>) {
    if (!jobId) return;
    busy = true;
    error = '';
    try {
      await fn(jobId);
      await load(jobId);
      onchanged();
    } catch (e: any) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const group = $derived(job ? groupOf(job.status) : null);
  // The job finished while the drawer was open: its done mark draws in, as on the dashboard.
  let landed = $state(false);
  let lastStatus: string | null = null;
  $effect(() => {
    const st: string | null = job?.status ?? null;
    untrack(() => {
      if (!st) landed = false;
      else if (lastStatus && !DONE.includes(lastStatus) && DONE.includes(st)) landed = true;
      lastStatus = st;
    });
  });
  // The running stage's percentage, so the track's connector fills along with the stage bar.
  const stagePct = $derived.by(() => {
    if (!job) return undefined;
    const r = currentRuns((job.stage_runs ?? []) as any[]).get(job.stage);
    if (r?.status !== 'running') return undefined;
    return (job.stage === 'transfer' ? fetched : bytes(r.progress))?.pct;
  });
  const steps = $derived(job ? jobSteps(job, stagePct) : []);
  // Follow the job: when it moves to another phase, drop any manual selection.
  const currentKey = $derived(steps.length ? steps[currentIndex(steps)].key : undefined);
  $effect(() => {
    currentKey;
    untrack(() => (selected = undefined));
  });
  const bytes = (p?: { bytes_done?: number; bytes_total?: number }) => {
    const total = p?.bytes_total ?? 0;
    const got = p?.bytes_done ?? 0;
    return total ? { pct: Math.round((got / total) * 100), got, total } : null;
  };
  const fetched = $derived(job ? bytes({ bytes_done: job.download_bytes_done, bytes_total: job.download_bytes_total }) : null);

  const DONE = ['completed', 'completed_with_warnings'];
  const size = fmtSize;
  const files = $derived<any[]>(job?.files ?? []);

  function took(r: any): string {
    if (!r.started_at) return '';
    const end = r.ended_at ? parseUtc(r.ended_at).getTime() : Date.now();
    return dur((end - parseUtc(r.started_at).getTime()) / 1000);
  }
  function dur(s: number, tenths = true): string {
    if (s < 60) return tenths ? `${s.toFixed(1)}s` : `${Math.max(1, Math.round(s))}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
</script>

{#snippet phaseCard(s: Step)}
  {@const runs = currentRuns((job.stage_runs ?? []) as any[])}
  <!-- No heading: the selected step's label right above names this card. -->
  <ul class="space-y-2.5 text-sm">
    {#each PHASES.find((p) => p.key === s.key)?.stages ?? [] as st (st)}
      {@const r = runs.get(st)}
      {@const kind = r
        ? runIcon(r.status)
        : st !== job.stage
          ? 'pending'
          : s.state === 'waiting'
            ? 'warning'
            : s.state === 'active'
              ? 'queued'
              : 'pending'}
      {@const bar = r?.status !== 'running' ? null : st === 'transfer' ? fetched : bytes(r.progress)}
      {@const list = stageList(st, r, files)}
      <li>
        <div class="flex items-center gap-2">
          <StatusIcon {kind} class="h-4 w-4" />
          <span class="flex-1 capitalize {r ? 'text-gray-800 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400'}"
            >{st.replaceAll('_', ' ')}</span
          >
          {#if r}
            <span class="whitespace-nowrap text-xs text-gray-500 tabular-nums dark:text-gray-400"
              >{#if took(r)}{`${r.ended_at ? '' : 'for '}${took(r)}`}{/if}{#if r.attempt > 1}{` · try ${r.attempt}`}{/if}</span
            >
          {/if}
        </div>
        {#if bar}
          {@const live = speeds[st] && now - speeds[st].at < SPEED_STALE_MS && bar.got < bar.total}
          <div class="mt-1.5 ms-6">
            <div class="h-1.5 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
              <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {bar.pct}%"></div>
            </div>
            <!-- Where it stands on the left, when it lands on the right. -->
            <div class="mt-1 flex items-baseline gap-x-1.5 text-xs text-gray-600 tabular-nums dark:text-gray-300">
              <span class="font-semibold text-gray-900 dark:text-white">{bar.pct}%</span>
              <span class="min-w-0 truncate">{[`${size(bar.got)} / ${size(bar.total)}`, live && `${size(speeds[st].bps)}/s`].filter(Boolean).join(' · ')}</span>
              {#if etas[st] != null && bar.got < bar.total}
                <span class="ms-auto ps-3 whitespace-nowrap">~{dur(etas[st], false)} left</span>
              {/if}
            </div>
          </div>
        {/if}
        {#if st === 'source_download' && r?.progress?.message}
          <p class="mt-1 ms-6 text-xs text-gray-500 dark:text-gray-400">{r.progress.message}</p>
        {/if}
        {#if st === 'check_library' && r?.progress?.eligibility}<LibraryVerdict progress={r.progress} />{/if}
        {#if list}<FileList {list} />{/if}
        <!-- The phase's banner below already says it when it is the job's own reason. -->
        {#if r?.error_detail && r.error_detail !== s.reason}
          <p class="mt-1 ms-6 text-xs text-red-700 dark:text-red-300" title={r.error_code}>{r.error_detail}</p>
        {/if}
      </li>
    {/each}
  </ul>
  {#if s.reason}
    <div
      class="mt-3 flex gap-2 rounded-md border p-2.5 text-sm {s.state === 'failed'
        ? 'border-red-400 bg-red-50 text-red-900 dark:border-red-500/50 dark:bg-red-500/15 dark:text-red-200'
        : 'border-amber-400 bg-amber-50 text-amber-900 dark:border-amber-500/50 dark:bg-amber-500/15 dark:text-amber-200'}"
    >
      <StatusIcon kind={s.state === 'failed' ? 'failed' : 'warning'} class="mt-0.5 h-4 w-4" />
      <div class="min-w-0 break-words">
        {s.reason}
        {#if job.error_code === 'no_transfer_config'}
          <a href="/sources/" class="mt-1.5 block font-medium underline underline-offset-2">Open source settings</a>
        {/if}
      </div>
    </div>
  {/if}
{/snippet}

<Drawer bind:open placement="right" class="w-full max-w-xl overflow-y-auto">
  {#if job}
    <div class="space-y-5">
      <div class="pr-8">
        <!-- Release names are one long token: allow breaks after the dots, not mid-word. -->
        <h3 class="text-lg font-semibold break-words text-gray-900 dark:text-white">
          {#each (job.config_snapshot?.title ?? '—').split('.') as part, i}{#if i}.<wbr />{/if}{part}{/each}
        </h3>
        <!-- Route: where the release comes from and which library it goes to. -->
        <div class="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
          {#each [['Source', job.config_snapshot?.source_name], ['Label', job.config_snapshot?.label], ['Library', job.library_name]] as [what, value], i}
            <!-- Arrow and the chip it points to wrap together, so no line ends on an arrow. -->
            <span class="inline-flex items-center gap-1.5">
              {#if i}
                <ChevronRightOutline class="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
              {/if}
              <span class="inline-flex items-baseline gap-1.5 rounded-md bg-gray-100 px-2 py-0.5 dark:bg-gray-700">
                <span class="text-xs text-gray-500 dark:text-gray-400">{what}</span>
                {#if value}
                  <span class="font-medium text-gray-900 dark:text-white">{value}</span>
                {:else}
                  <span class="text-gray-500 italic dark:text-gray-400">none</span>
                {/if}
              </span>
            </span>
          {/each}
        </div>
        <p class="mt-2 flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
          Created {ago(job.created_at)}
          {#if DONE.includes(job.status) && job.ended_at}
            <span aria-hidden="true">·</span>
            <StatusIcon kind={job.status === 'completed' ? 'done' : 'warning'} draw={landed} class="h-3.5 w-3.5" />
            <span class="text-gray-700 dark:text-gray-200"
              >Done in {dur((parseUtc(job.ended_at).getTime() - parseUtc(job.created_at).getTime()) / 1000, false)}</span
            >
          {/if}
        </p>
      </div>

      {#if error}<Alert color="red">{error}</Alert>{/if}

      <StepTrack {steps} bind:selected detail={phaseCard} />

      <div class="flex flex-wrap items-center gap-2">
        {#if group === 'failed'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.retry)}>Retry</Button>
          <Button size="xs" color="alternative" disabled={busy} onclick={() => act(endpoints.jobs.retryImport)}>Retry import</Button>
        {/if}
        {#if job.status === 'waiting_approval'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.approve)}>Start</Button>
        {/if}
        {#if ['source_download', 'check_library'].includes(job.stage) && !['running', 'cancelled'].includes(job.status) && !job.config_snapshot?.skip_library}
          <Button
            size="xs"
            color="alternative"
            disabled={busy}
            title="Process it without asking the library first, e.g. a pack of several movies. At import the library matches each file on its own."
            onclick={() => act(endpoints.jobs.skipLibrary)}>Skip library check</Button
          >
        {/if}
        {#if !['running', 'queued', 'waiting_source'].includes(job.status)}
          <Button
            size="xs"
            color="alternative"
            disabled={busy}
            title="Run every stage again from the start and download the files again"
            onclick={() => act(endpoints.jobs.restart)}>Restart</Button
          >
        {/if}
        {#if job.status === 'running' || job.status === 'queued'}
          <Button size="xs" color="alternative" disabled={busy} onclick={() => act(endpoints.jobs.pause)}>Pause</Button>
        {/if}
        {#if job.status === 'paused'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.resume)}>Resume</Button>
        {/if}
        {#if group === 'active'}
          <!-- Destructive: kept apart from the rest and quieter than the primary action. -->
          <Button size="xs" color="red" outline class="ms-auto" disabled={busy} onclick={() => act(endpoints.jobs.cancel)}>Cancel job</Button>
        {/if}
      </div>

      <EventTimeline {events} />
    </div>
  {:else if error}
    <Alert color="red">{error}</Alert>
  {:else}
    <p class="text-gray-600 dark:text-gray-300">Loading…</p>
  {/if}
</Drawer>

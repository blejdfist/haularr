<script lang="ts">
  import { untrack } from 'svelte';
  import { Drawer, Button, Alert } from 'flowbite-svelte';
  import { endpoints } from '$lib/api/client';
  import { subscribe, coalesce, type JobEvent } from '$lib/live';
  import { groupOf, parseUtc, ago, runIcon, fmtSize, SPEED_STALE_MS, type IconKind } from '$lib/status';
  import StatusIcon from '$lib/components/StatusIcon.svelte';
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

  async function load(id: string) {
    error = '';
    try {
      job = await endpoints.jobs.get(id);
      events = job.events ?? [];
      for (const r of job.stage_runs ?? [])
        if (r.status === 'running') sample(r.stage, r.stage === 'download' ? fetched : bytes(r.progress));
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
  const steps = $derived(job ? jobSteps(job) : []);
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

  const fmt = (s: string | null) => (s ? parseUtc(s).toLocaleString() : '');
  const size = fmtSize;
  const FILE_ICON: Record<string, IconKind> = {
    pending: 'pending',
    in_progress: 'running',
    completed: 'done',
    verified: 'done',
    failed: 'failed',
  };
  const files = $derived<any[]>(job?.files ?? []);
  const filesTotal = $derived(files.reduce((n, f) => n + (f.size_bytes ?? 0), 0));
  // Release folder shared by every file: shown once above the list, not on each row.
  const filesRoot = $derived.by(() => {
    const first = files[0]?.remote_relpath ?? '';
    const top = first.includes('/') ? first.slice(0, first.indexOf('/') + 1) : '';
    return top && files.every((f) => f.remote_relpath.startsWith(top)) ? top : '';
  });
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
  <h5 class="font-semibold text-gray-900 dark:text-white">{s.label}</h5>
  <ul class="mt-2 space-y-2 text-sm">
    {#each PHASES.find((p) => p.key === s.key)?.stages ?? [] as st (st)}
      {@const r = runs.get(st)}
      {@const kind = r ? runIcon(r.status) : st === job.stage && s.state === 'waiting' ? 'warning' : 'pending'}
      {@const bar = r?.status !== 'running' ? null : st === 'download' ? fetched : bytes(r.progress)}
      <li>
        <div class="flex items-center gap-2">
          <StatusIcon {kind} class="h-4 w-4" />
          <span class="flex-1 capitalize {r ? 'text-gray-800 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400'}"
            >{st.replaceAll('_', ' ')}</span
          >
          {#if r}
            <span class="whitespace-nowrap font-mono text-xs text-gray-600 dark:text-gray-300"
              >{#if took(r)}{`${r.ended_at ? '' : 'for '}${took(r)}`}{/if}{#if r.attempt > 1}{` · try ${r.attempt}`}{/if}</span
            >
          {/if}
        </div>
        {#if bar}
          <div class="mt-1.5 ms-6">
            <div class="h-1.5 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
              <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {bar.pct}%"></div>
            </div>
            <div class="mt-1 text-xs text-gray-600 dark:text-gray-300">
              {bar.pct}% · {size(bar.got)} / {size(bar.total)}{#if speeds[st] && now - speeds[st].at < SPEED_STALE_MS && bar.got < bar.total}{` · ${size(speeds[st].bps)}/s`}{/if}{#if etas[st] != null && bar.got < bar.total}{` · ~${dur(etas[st], false)} left`}{/if}
            </div>
          </div>
        {/if}
        {#if r?.error_detail}
          <p class="mt-0.5 ms-6 text-xs text-red-700 dark:text-red-300">{r.error_code}: {r.error_detail}</p>
        {/if}
      </li>
    {/each}
  </ul>
  {#if s.reason}
    <div
      class="mt-3 rounded-md border p-2.5 text-sm {s.state === 'failed'
        ? 'border-red-400 bg-red-50 text-red-900 dark:border-red-500/50 dark:bg-red-500/15 dark:text-red-200'
        : 'border-amber-400 bg-amber-50 text-amber-900 dark:border-amber-500/50 dark:bg-amber-500/15 dark:text-amber-200'}"
    >
      <span class="font-semibold">{s.state === 'failed' ? 'Failed' : 'Blocked'}:</span> {s.reason}
      {#if job.error_code === 'no_transfer_config'}
        <a href="/sources/" class="mt-1.5 block font-medium underline">Open source settings</a>
      {/if}
    </div>
  {/if}
{/snippet}

<Drawer bind:open placement="right" class="w-full max-w-xl overflow-y-auto">
  {#if job}
    <div class="space-y-5">
      <div class="pr-8">
        <h3 class="text-lg font-semibold break-words text-gray-900 dark:text-white">{job.config_snapshot?.title ?? '—'}</h3>
        <!-- Route: where the release comes from and which library it goes to. -->
        <div class="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
          {#each [['Source', job.config_snapshot?.source_name], ['Label', job.config_snapshot?.label], ['Library', job.library_name]] as [what, value], i}
            {#if i}
              <svg viewBox="0 0 20 20" class="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true"
                ><path fill="currentColor" d="M7.3 4.3a1 1 0 0 1 1.4 0l5 5a1 1 0 0 1 0 1.4l-5 5a1 1 0 1 1-1.4-1.4L11.6 10 7.3 5.7a1 1 0 0 1 0-1.4Z" /></svg
              >
            {/if}
            <span class="inline-flex items-baseline gap-1.5 rounded-md bg-gray-100 px-2 py-0.5 dark:bg-gray-700">
              <span class="text-xs text-gray-500 dark:text-gray-400">{what}</span>
              {#if value}
                <span class="font-medium text-gray-900 dark:text-white">{value}</span>
              {:else}
                <span class="text-gray-500 italic dark:text-gray-400">none</span>
              {/if}
            </span>
          {/each}
        </div>
        <p class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">Created {ago(job.created_at)}</p>
      </div>

      {#if error}<Alert color="red">{error}</Alert>{/if}

      <StepTrack {steps} bind:selected detail={phaseCard} />

      <div class="flex flex-wrap gap-2">
        {#if group === 'failed'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.retry)}>Retry</Button>
          <Button size="xs" color="alternative" disabled={busy} onclick={() => act(endpoints.jobs.retryImport)}>Retry import</Button>
        {/if}
        {#if job.status !== 'running' && job.status !== 'queued'}
          <Button
            size="xs"
            color="alternative"
            disabled={busy}
            title="Run every stage again from the start and download the files again"
            onclick={() => act(endpoints.jobs.restart)}>Restart</Button
          >
        {/if}
        {#if job.status === 'running' || job.status === 'queued'}
          <Button size="xs" color="yellow" disabled={busy} onclick={() => act(endpoints.jobs.pause)}>Pause</Button>
        {/if}
        {#if job.status === 'paused'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.resume)}>Resume</Button>
        {/if}
        {#if group === 'active'}
          <Button size="xs" color="red" disabled={busy} onclick={() => act(endpoints.jobs.cancel)}>Cancel</Button>
        {/if}
      </div>

      <section>
        <h4 class="mb-2 flex items-baseline gap-2 font-semibold text-gray-900 dark:text-white">
          Files
          {#if files.length}
            <span class="text-sm font-normal text-gray-600 dark:text-gray-300"
              >{files.length} · {size(filesTotal)}</span
            >
          {/if}
        </h4>
        {#if filesRoot}
          <p class="-mt-1 mb-2 truncate text-xs text-gray-500 dark:text-gray-400" title={filesRoot}>
            in {filesRoot.slice(0, -1)}
          </p>
        {/if}
        {#if files.length}
          <ul class="divide-y divide-gray-200 rounded-lg border border-gray-200 text-sm dark:divide-gray-700 dark:border-gray-700">
            {#each files as f (f.id)}
              {@const rel = f.remote_relpath.slice(filesRoot.length)}
              {@const slash = rel.lastIndexOf('/')}
              {@const active = f.transfer_status === 'in_progress'}
              {@const pct = f.size_bytes ? Math.round(((f.bytes_received ?? 0) / f.size_bytes) * 100) : 0}
              <li class="flex items-start gap-2.5 px-3 py-2">
                <StatusIcon kind={FILE_ICON[f.transfer_status] ?? 'pending'} class="mt-0.5 h-4 w-4" />
                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline gap-2">
                    <span class="flex-1 truncate font-medium text-gray-900 dark:text-white" title={f.remote_relpath}
                      >{rel.slice(slash + 1)}</span
                    >
                    <span class="whitespace-nowrap text-xs text-gray-600 tabular-nums dark:text-gray-300"
                      >{active ? `${size(f.bytes_received)} / ` : ''}{size(f.size_bytes)}</span
                    >
                  </div>
                  {#if slash > 0}
                    <div class="truncate text-xs text-gray-500 dark:text-gray-400" title={f.remote_relpath}>
                      {rel.slice(0, slash)}
                    </div>
                  {/if}
                  {#if active}
                    <div class="mt-1.5 h-1 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
                      <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {pct}%"></div>
                    </div>
                  {:else if f.transfer_status === 'failed'}
                    <div class="text-xs text-red-700 dark:text-red-300">Transfer failed</div>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="text-sm text-gray-600 dark:text-gray-300">Files are listed once the download starts.</p>
        {/if}
      </section>

      <details>
        <summary class="cursor-pointer font-semibold text-gray-900 dark:text-white">Events ({events.length})</summary>
        <ul class="mt-2 space-y-2 text-sm">
          {#each events as e}
            <li class={e.severity === 'error' ? 'text-red-700 dark:text-red-300' : 'text-gray-800 dark:text-gray-100'}>
              <span class="text-gray-600 dark:text-gray-300">{fmt(e.created_at)}</span> <span class="font-mono">{e.kind}</span> {e.message}
              {#if e.severity === 'error' && e.details}
                <pre class="mt-1 text-xs whitespace-pre-wrap">{JSON.stringify(e.details, null, 2)}</pre>
              {/if}
            </li>
          {:else}
            <li class="text-gray-600 dark:text-gray-300">No events.</li>
          {/each}
        </ul>
      </details>
    </div>
  {:else if error}
    <Alert color="red">{error}</Alert>
  {:else}
    <p class="text-gray-600 dark:text-gray-300">Loading…</p>
  {/if}
</Drawer>

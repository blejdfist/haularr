<script lang="ts">
  import { untrack } from 'svelte';
  import { Drawer, Button, Alert } from 'flowbite-svelte';
  import { endpoints } from '$lib/api/client';
  import { groupOf, parseUtc, ago } from '$lib/status';
  import { PHASES, jobSteps } from '$lib/pipeline';
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

  async function load(id: string) {
    error = '';
    try {
      [job, events] = await Promise.all([endpoints.jobs.get(id), endpoints.jobs.events(id)]);
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
        load(id);
      });
      // Live view: refresh while open so stage changes show up without reopening.
      const t = setInterval(() => load(id), 3000);
      return () => clearInterval(t);
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
  const fetched = $derived.by(() => {
    const files = job?.files ?? [];
    const total = files.reduce((n: number, f: any) => n + (f.size_bytes ?? 0), 0);
    const got = files.reduce((n: number, f: any) => n + (f.bytes_received ?? 0), 0);
    return total ? { pct: Math.round((got / total) * 100), got, total } : null;
  });

  const fmt = (s: string | null) => (s ? parseUtc(s).toLocaleString() : '');
  const size = (n: number | null) => (n == null ? '' : `${(n / 1048576).toFixed(1)} MB`);
  function took(r: any): string {
    if (!r.started_at) return '';
    const end = r.ended_at ? parseUtc(r.ended_at).getTime() : Date.now();
    const s = (end - parseUtc(r.started_at).getTime()) / 1000;
    if (s < 60) return `${s.toFixed(1)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
  const runColor = (status: string) =>
    status === 'failed' ? 'text-red-700 dark:text-red-300' : status === 'running' ? 'text-blue-700 dark:text-blue-300' : 'text-gray-600 dark:text-gray-300';
  // Latest run per stage only: the card shows current status, not attempt history.
  const runsFor = (s: Step) => {
    const stages = PHASES.find((p) => p.key === s.key)?.stages ?? [];
    const latest = new Map<string, any>();
    for (const r of job?.stage_runs ?? []) {
      if (!stages.includes(r.stage)) continue;
      const prev = latest.get(r.stage);
      if (!prev || r.attempt > prev.attempt || (r.attempt === prev.attempt && (r.started_at ?? '') > (prev.started_at ?? '')))
        latest.set(r.stage, r);
    }
    return stages.filter((st) => latest.has(st)).map((st) => latest.get(st));
  };
</script>

{#snippet phaseCard(s: Step)}
  {@const runs = runsFor(s)}
  <div class="flex items-baseline justify-between">
    <h5 class="font-semibold text-gray-900 dark:text-white">{s.label}</h5>
    <span class="text-xs text-gray-600 dark:text-gray-300">{s.state}</span>
  </div>
  {#if runs.length}
    <ul class="mt-2 space-y-1.5 text-sm">
      {#each runs as r}
        <li>
          <div class="flex justify-between gap-2">
            <span class="text-gray-800 dark:text-gray-100">{r.stage.replaceAll('_', ' ')}</span>
            <span class="whitespace-nowrap font-mono text-xs {runColor(r.status)}"
              >{r.status}{#if took(r)}{` · ${r.ended_at ? '' : 'for '}${took(r)}`}{/if}{#if r.attempt > 1}{` · try ${r.attempt}`}{/if}</span
            >
          </div>
          {#if r.error_detail}
            <p class="mt-0.5 text-xs text-red-700 dark:text-red-300">{r.error_code}: {r.error_detail}</p>
          {/if}
        </li>
      {/each}
    </ul>
  {:else}
    <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">Not started.</p>
  {/if}
  {#if s.key === 'fetch' && fetched && s.state !== 'done'}
    <div class="mt-2 text-xs text-gray-600 dark:text-gray-300">{fetched.pct}% · {size(fetched.got)} / {size(fetched.total)}</div>
    <div class="mt-1 h-1.5 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
      <div class="h-full bg-blue-600" style="width: {fetched.pct}%"></div>
    </div>
  {/if}
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
        <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">
          {job.config_snapshot?.source_name ?? '—'} · {job.config_snapshot?.label ?? '—'} → {job.library_name ?? '—'} · created {ago(job.created_at)}
        </p>
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
        <h4 class="mb-2 font-semibold text-gray-900 dark:text-white">Files</h4>
        <ul class="space-y-1 text-sm">
          {#each job.files ?? [] as f}
            <li class="flex justify-between gap-2">
              <span class="break-all text-gray-800 dark:text-gray-100">{f.remote_relpath}</span>
              <span class="whitespace-nowrap text-gray-600 dark:text-gray-300">{f.transfer_status} · {size(f.bytes_received)} / {size(f.size_bytes)}</span>
            </li>
          {:else}
            <li class="text-gray-600 dark:text-gray-300">No files.</li>
          {/each}
        </ul>
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

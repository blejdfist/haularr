<script lang="ts">
  import { untrack } from 'svelte';
  import { Drawer, Button, Alert } from 'flowbite-svelte';
  import { ChevronRightOutline, FolderSolid } from 'flowbite-svelte-icons';
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

  const DONE = ['completed', 'completed_with_warnings'];
  /** Event time: clock time today, date and time otherwise. The full stamp is in the tooltip. */
  function when(s: string): string {
    const d = parseUtc(s);
    const today = d.toDateString() === new Date().toDateString();
    return d.toLocaleString(undefined, today ? { hour: '2-digit', minute: '2-digit' } : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  const hasDetails = (d: unknown) => d != null && (typeof d !== 'object' || Object.keys(d).length > 0);
  /** A file's error repeats its path first; the row already shows the path. */
  const unprefix = (detail: string, path: string) => {
    const head = [path, basename(path)].find((p) => detail.startsWith(`${p}: `));
    return head ? detail.slice(head.length + 2) : detail;
  };
  const size = fmtSize;
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
  const files = $derived<any[]>(job?.files ?? []);
  // Every stage's list uses one row shape, so they all render alike (see the fileList snippet).
  type Row = { key: string; path: string; kind: IconKind; meta?: string; note?: string; tone?: 'error' | 'warn'; pct?: number };
  type List = { caption: string[]; rows: Row[]; empty?: string };

  function sizeRow(key: string, path: string, kind: IconKind, total: number, done: number, live: boolean): Row {
    const pct = total ? Math.round((done / total) * 100) : 0;
    return { key, path, kind, meta: live ? `${pct}% · ${size(done)} / ${size(total)}` : size(total), pct: live ? pct : undefined };
  }
  const basename = (f: string) => f.slice(f.lastIndexOf('/') + 1);

  /** The list under a stage: what it worked on, file by file. Null when it has none. */
  function stageList(st: string, r: any): List | null {
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
  // Release folder shared by every file: shown once above the list, not on each row.
  function commonRoot(paths: string[]): string {
    const first = paths[0] ?? '';
    const top = first.includes('/') ? first.slice(0, first.indexOf('/') + 1) : '';
    return top && paths.every((x) => x.startsWith(top)) ? top : '';
  }
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

{#snippet fileList(list: List)}
  {@const root = commonRoot(list.rows.map((f) => f.path))}
  <div class="mt-1.5 ms-6 text-xs">
    {#each list.caption as line}
      <p class="mb-1 truncate text-gray-600 dark:text-gray-300" title={line}>{line}</p>
    {/each}
    {#if list.rows.length}
      <ul class="divide-y divide-gray-200 overflow-hidden rounded-md border border-gray-200 bg-white dark:divide-gray-700 dark:border-gray-700 dark:bg-gray-800">
        {#if root}
          <!-- The release folder every file sits in, as the list's header. -->
          <li class="flex items-center gap-2 bg-gray-50 px-2.5 py-1.5 text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
            <FolderSolid class="h-3.5 w-3.5 shrink-0 text-gray-400 dark:text-gray-500" aria-hidden="true" />
            <span class="min-w-0 truncate" title={root.slice(0, -1)}>{root.slice(0, -1)}</span>
          </li>
        {/if}
        {#each list.rows as f (f.key)}
          {@const rel = f.path.slice(root.length)}
          {@const slash = rel.lastIndexOf('/')}
          <li class="flex items-start gap-2 px-2.5 py-1.5">
            <StatusIcon kind={f.kind} class="mt-px h-3.5 w-3.5 shrink-0" />
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-2">
                <!-- Folder and name on one line; a long folder shrinks before the name does. -->
                <span class="flex min-w-0 flex-1 text-gray-900 dark:text-white" title={f.path}>
                  {#if slash > 0}<span class="min-w-0 shrink-[999] truncate text-gray-500 dark:text-gray-400"
                      >{rel.slice(0, slash + 1)}</span
                    >{/if}<span class="min-w-0 truncate">{rel.slice(slash + 1)}</span>
                </span>
                {#if f.meta}<span class="whitespace-nowrap text-gray-600 tabular-nums dark:text-gray-300">{f.meta}</span>{/if}
              </div>
              {#if f.pct != null}
                <div class="mt-1 h-1 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
                  <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {f.pct}%"></div>
                </div>
              {/if}
              {#if f.note}
                <p class={f.tone === 'error' ? 'text-red-700 dark:text-red-300' : f.tone === 'warn' ? 'text-amber-700 dark:text-amber-300' : 'text-gray-500 dark:text-gray-400'}>
                  {f.note}
                </p>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {:else if list.empty}
      <p class="text-gray-500 dark:text-gray-400">{list.empty}</p>
    {/if}
  </div>
{/snippet}

{#snippet phaseCard(s: Step)}
  {@const runs = currentRuns((job.stage_runs ?? []) as any[])}
  <!-- No heading: the selected step's label right above names this card. -->
  <ul class="space-y-2.5 text-sm">
    {#each PHASES.find((p) => p.key === s.key)?.stages ?? [] as st (st)}
      {@const r = runs.get(st)}
      {@const kind = r ? runIcon(r.status) : st === job.stage && s.state === 'waiting' ? 'warning' : 'pending'}
      {@const bar = r?.status !== 'running' ? null : st === 'transfer' ? fetched : bytes(r.progress)}
      {@const list = stageList(st, r)}
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
          <div class="mt-1.5 ms-6">
            <div class="h-1.5 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
              <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {bar.pct}%"></div>
            </div>
            <div class="mt-1 text-xs text-gray-600 dark:text-gray-300">
              {bar.pct}% · {size(bar.got)} / {size(bar.total)}{#if speeds[st] && now - speeds[st].at < SPEED_STALE_MS && bar.got < bar.total}{` · ${size(speeds[st].bps)}/s`}{/if}{#if etas[st] != null && bar.got < bar.total}{` · ~${dur(etas[st], false)} left`}{/if}
            </div>
          </div>
        {/if}
        {#if st === 'source_download' && r?.progress?.message}
          <p class="mt-1 ms-6 text-xs text-gray-500 dark:text-gray-400">{r.progress.message}</p>
        {/if}
        {#if st === 'check_library' && r?.progress?.eligibility}
          {@const p = r.progress}
          {@const parsed = p.match?.parsed ?? {}}
          <dl class="mt-1 ms-6 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {#if p.eligibility === 'skipped_by_user'}
              <dt class="text-gray-500 dark:text-gray-400">Verdict</dt><dd class="text-gray-800 dark:text-gray-100">Skipped by you</dd>
            {:else}
              {#if p.library}<dt class="text-gray-500 dark:text-gray-400">Library</dt><dd class="text-gray-800 dark:text-gray-100">{p.library}</dd>{/if}
              <dt class="text-gray-500 dark:text-gray-400">Verdict</dt>
              <dd class="text-gray-800 dark:text-gray-100">{p.eligibility.replaceAll('_', ' ')}{#if p.reason}<span class="text-gray-500 dark:text-gray-400">{` · ${p.reason}`}</span>{/if}</dd>
              {#if p.match}
                <dt class="text-gray-500 dark:text-gray-400">Parsed as</dt>
                <dd class="text-gray-800 dark:text-gray-100">
                  {parsed.title ?? '—'}{#if parsed.year}{` (${parsed.year})`}{/if}{#if parsed.season != null}{` · S${String(parsed.season).padStart(2, '0')}`}{/if}{#if parsed.episodes}{` E${parsed.episodes.join(', E')}`}{:else if parsed.full_season}{' · full season'}{/if}{#if parsed.edition}{` · ${parsed.edition}`}{/if}
                </dd>
                {#if parsed.quality || parsed.group}
                  <dt class="text-gray-500 dark:text-gray-400">Release</dt>
                  <dd class="text-gray-800 dark:text-gray-100">{[parsed.quality, parsed.group].filter(Boolean).join(' · ')}</dd>
                {/if}
                <dt class="text-gray-500 dark:text-gray-400">Matched</dt>
                <dd class="text-gray-800 dark:text-gray-100">
                  {p.match.catalog_id != null ? `${p.match.media_type} #${p.match.catalog_id}` : 'no library entry'}{#if p.match.episode_ids}{` · ${p.match.episode_ids} episodes`}{/if}
                </dd>
              {/if}
              {#if p.evidence?.has_file != null}
                <dt class="text-gray-500 dark:text-gray-400">In library</dt>
                <dd class="text-gray-800 dark:text-gray-100">{p.evidence.has_file ? 'has a file' : 'no file'}{#if p.evidence.missing_episode_ids?.length}{` · ${p.evidence.missing_episode_ids.length} episodes missing`}{/if}</dd>
              {/if}
            {/if}
          </dl>
        {/if}
        {#if list}{@render fileList(list)}{/if}
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

      <details class="group border-t border-gray-200 pt-4 dark:border-gray-700">
        <summary
          class="flex cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-semibold text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 dark:text-white [&::-webkit-details-marker]:hidden"
        >
          <ChevronRightOutline
            class="h-4 w-4 text-gray-500 transition-transform group-open:rotate-90 motion-reduce:transition-none dark:text-gray-400"
            aria-hidden="true"
          />
          Events
          <span class="font-normal text-gray-500 tabular-nums dark:text-gray-400">{events.length}</span>
        </summary>
        {#if events.length}
          <!-- A timeline: one rail, a dot per event colored by severity. -->
          <ol class="mt-3 ms-2 border-s border-gray-200 text-sm dark:border-gray-700">
            {#each events as e}
              <li class="relative ps-4 pb-3 last:pb-0">
                <span
                  class="absolute -start-1 top-1.5 h-2 w-2 rounded-full ring-4 ring-white dark:ring-gray-800 {e.severity === 'error'
                    ? 'bg-red-500'
                    : e.severity === 'warning'
                      ? 'bg-amber-500'
                      : 'bg-gray-400 dark:bg-gray-500'}"
                ></span>
                <time class="block text-xs text-gray-500 tabular-nums dark:text-gray-400" datetime={e.created_at} title={parseUtc(e.created_at).toLocaleString()}
                  >{when(e.created_at)}</time
                >
                <p class="break-words {e.severity === 'error' ? 'text-red-700 dark:text-red-300' : 'text-gray-800 dark:text-gray-100'}" title={e.kind}>{e.message}</p>
                {#if e.severity === 'error' && hasDetails(e.details)}
                  <pre class="mt-1 overflow-x-auto rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap text-gray-700 dark:bg-gray-900/40 dark:text-gray-300">{JSON.stringify(e.details, null, 2)}</pre>
                {/if}
              </li>
            {/each}
          </ol>
        {:else}
          <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Nothing logged yet.</p>
        {/if}
      </details>
    </div>
  {:else if error}
    <Alert color="red">{error}</Alert>
  {:else}
    <p class="text-gray-600 dark:text-gray-300">Loading…</p>
  {/if}
</Drawer>

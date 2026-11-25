<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button, Alert } from 'flowbite-svelte';
  import { SearchOutline } from 'flowbite-svelte-icons';
  import { endpoints, type Job } from '$lib/api/client';
  import { STATUS_GROUPS, jobIcon, ago, groupCount as sum } from '$lib/status';
  import { subscribe, coalesce, type JobEvent } from '$lib/live';
  import { jobSteps, reasonFor } from '$lib/pipeline';
  import StatusIcon from '$lib/components/StatusIcon.svelte';
  import StepDots from '$lib/components/steps/StepDots.svelte';
  import JobDrawer from '$lib/components/JobDrawer.svelte';

  const FILTERS = ['all', 'active', 'failed', 'done', 'skipped'] as const;
  type Filter = (typeof FILTERS)[number];
  const EMPTY: Record<Filter, string> = {
    all: 'No transfers yet',
    active: 'No active transfers',
    failed: 'No failed transfers',
    done: 'No completed transfers',
    skipped: 'Nothing skipped',
  };

  const filter: Filter = $derived.by(() => {
    const f = page.url.searchParams.get('f') as Filter;
    return FILTERS.includes(f) ? f : 'all';
  });

  let jobs = $state<Job[]>([]);
  let skipped = $state<any[]>([]);
  let dash = $state<any>(null);
  let error = $state('');
  let search = $state('');
  let progress = $state<Record<string, { stage: string; pct: number }>>({});
  // Jobs seen finishing while the page is open: their row acknowledges the arrival once.
  let arrived = $state<Record<string, true>>({});
  const DONE = ['completed', 'completed_with_warnings'];
  // Tables sit on the page, not in a card: a quiet label row, hairlines between rows.
  const HEAD_ROW = 'border-b border-gray-200 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400';
  const TH = 'px-4 pt-1 pb-2.5 font-medium';
  let drawerOpen = $state(false);
  let drawerJob = $state<string | null>(null);

  let loaded = $state(false);

  const by: Record<string, number> = $derived(dash?.jobs?.by_status ?? {});
  // Tab counts. Skipped lists source items, not jobs, and the dashboard has no count for those.
  const counts: Partial<Record<Filter, number>> = $derived({
    all: Object.values(by).reduce((n, c) => n + c, 0),
    active: sum(by, 'active'),
    failed: sum(by, 'failed'),
    done: sum(by, 'done'),
  });
  const pill = (f: Filter, n: number) =>
    f === 'failed' && n
      ? 'bg-red-500/15 text-red-600 dark:text-red-400'
      : f === 'active' && n
        ? 'bg-blue-500/15 text-blue-700 dark:text-blue-300'
        : 'bg-gray-200 dark:bg-gray-700/60 text-gray-500 dark:text-gray-400';

  type SourceHealth = { id: string; name: string; last_scan_at: string | null; last_scan_error: string | null };
  const sources: SourceHealth[] = $derived(dash?.source_health ?? []);
  const broken = $derived(sources.filter((s) => s.last_scan_error));
  const lastScan = $derived(
    sources
      .map((s) => s.last_scan_at)
      .filter((t): t is string => !!t)
      .sort()
      .at(-1) ?? null,
  );
  const q = $derived(search.trim().toLowerCase());
  const shownJobs = $derived(jobs.filter((j) => !q || (j.title ?? '').toLowerCase().includes(q)));
  const shownSkipped = $derived(skipped.filter((i) => !q || (i.title ?? '').toLowerCase().includes(q)));

  // Last status|stage seen per job: a change there (or a job we have not seen) means the list,
  // its order or the stat cards may change, so refetch. Progress alone is patched in place.
  let seen = new Map<string, string>();
  const key = (j: { status: string; stage: string }) => `${j.status}|${j.stage}`;

  async function load() {
    const f = filter;
    try {
      const [d, list] = await Promise.all([
        endpoints.dashboard.get(),
        f === 'skipped'
          ? endpoints.sourceItems.skipped({ limit: 100 })
          : endpoints.jobs.list({ limit: 100, ...(f !== 'all' && { status: STATUS_GROUPS[f] }) }),
      ]);
      if (f !== filter) return; // filter changed while loading
      dash = d;
      if (f === 'skipped') skipped = list.items;
      else jobs = list.items as Job[];
      for (const j of jobs) seen.set(j.id, key(j));
      error = '';
    } catch (e: any) {
      error = e.message;
    }
    loaded = true;
  }

  // Reload on filter change; afterwards the server's event stream says when jobs changed.
  $effect(() => {
    filter;
    jobs = [];
    skipped = [];
    loaded = false;
    load();
  });

  const refetch = coalesce(load);

  // Job change stream. Refetch on (re)connect, so changes missed while disconnected show up.
  $effect(() =>
    subscribe('/events/jobs', {
      open: refetch,
      job: (e: JobEvent) => {
        if (e.progress != null) progress[e.id] = { stage: e.stage, pct: e.progress };
        else delete progress[e.id];
        const prev = seen.get(e.id);
        if (prev && DONE.includes(e.status) && !DONE.includes(prev.split('|')[0])) {
          arrived[e.id] = true;
          setTimeout(() => delete arrived[e.id], 2500);
        }
        if (prev !== key(e)) {
          seen.set(e.id, key(e));
          refetch();
        }
      },
    }),
  );

  function setFilter(next: Filter) {
    goto(next === 'all' ? '?' : `?f=${next}`, { replaceState: true, keepFocus: true, noScroll: true });
  }

  function openJob(id: string) {
    drawerJob = id;
    drawerOpen = true;
  }

  async function fetchAnyway(id: string) {
    try {
      await endpoints.sourceItems.queue(id, true);
      await load();
    } catch (e: any) {
      error = e.message;
    }
  }
</script>

{#snippet steps(j: Job)}
  <!-- Live progress until the stream sends some; transfer bytes come with the job itself, so a reload doesn't show 0%. -->
  {@const live = progress[j.id]?.stage === j.stage ? progress[j.id].pct : undefined}
  {@const listed = j.stage === 'transfer' && j.download_bytes_total ? Math.round((j.download_bytes_done * 100) / j.download_bytes_total) : undefined}
  <StepDots steps={jobSteps(j, live ?? listed)} />
{/snippet}

<div class="space-y-5">
  <header class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
    <div>
      <h1 class="text-2xl font-bold">Dashboard</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
        {#if dash}{dash.jobs.completed_7d} completed in the last 7 days{:else}&nbsp;{/if}
      </p>
    </div>
    {#if dash}
      <a
        href="/sources/"
        class="-mx-3 inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:outline-none"
      >
        <span
          class="h-2 w-2 shrink-0 rounded-full {broken.length ? 'bg-red-500' : sources.length ? 'bg-green-500' : 'bg-gray-500'}"
        ></span>
        {#if !sources.length}
          No sources yet
        {:else if broken.length}
          {broken.length === 1 ? `${broken[0].name}: last scan failed` : `${broken.length} sources failing to scan`}
        {:else}
          {sources.length === 1 ? sources[0].name : `${sources.length} sources`} OK{#if lastScan}<span class="text-gray-500"
              >&nbsp;· scanned {ago(lastScan)}</span
            >{/if}
        {/if}
      </a>
    {/if}
  </header>

  <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-3 border-b border-gray-200 dark:border-gray-700">
    <nav class="-mb-px flex max-w-full [scrollbar-width:none] overflow-x-auto" aria-label="Filter transfers">
      {#each FILTERS as x}
        {@const n = counts[x]}
        <button
          type="button"
          aria-pressed={filter === x}
          onclick={() => setFilter(x)}
          class="flex items-center gap-2 border-b-2 px-3 pt-1 pb-3 text-sm font-medium whitespace-nowrap capitalize transition-colors duration-150 focus-visible:bg-gray-800 focus-visible:outline-none {filter ===
          x
            ? 'border-primary-500 text-gray-900 dark:text-white'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:border-gray-400 hover:text-gray-700 dark:hover:border-gray-500 dark:hover:text-gray-200'}"
        >
          {x}
          {#if n != null && dash}
            <span class="min-w-6 rounded-full px-1.5 py-0.5 text-center text-xs tabular-nums {pill(x, n)}">{n}</span>
          {/if}
        </button>
      {/each}
    </nav>
    <label class="relative mb-2.5 w-full sm:w-64">
      <span class="sr-only">Filter by title</span>
      <SearchOutline class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-500" />
      <input
        type="search"
        placeholder="Filter by title"
        bind:value={search}
        class="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white py-2 pr-3 pl-9 text-sm text-gray-900 dark:bg-gray-800 dark:text-white placeholder:text-gray-400 focus:border-primary-500 focus:ring-primary-500"
      />
    </label>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#if filter === 'skipped'}
    <table class="w-full text-left text-sm">
      <thead class="hidden sm:table-header-group">
        <tr class={HEAD_ROW}>
          <th scope="col" class="{TH} pl-3">Title</th>
          <th scope="col" class={TH}>Source / label</th>
          <th scope="col" class={TH}>Reason</th>
          <th scope="col" class="{TH} pr-3"><span class="sr-only">Action</span></th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200 dark:divide-gray-800">
        {#each shownSkipped as i (i.id)}
          <tr class="transition-colors duration-150 hover:bg-gray-100 dark:hover:bg-gray-800/50">
            <td class="py-3.5 pr-4 pl-3 font-medium break-words text-gray-900 dark:text-gray-100">{i.title ?? '—'}</td>
            <td class="hidden px-4 py-3.5 text-gray-500 dark:text-gray-400 sm:table-cell">{i.source_name ?? i.source_id} · {(i.labels ?? []).join(', ') || '—'}</td>
            <td class="hidden px-4 py-3.5 whitespace-nowrap text-gray-500 dark:text-gray-400 sm:table-cell">Already in library</td>
            <td class="py-3.5 pr-3 pl-4 text-right"><Button size="xs" color="alternative" class="whitespace-nowrap" onclick={() => fetchAnyway(i.id)}>Fetch anyway</Button></td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if loaded && !shownSkipped.length}
      <p class="py-10 text-center text-gray-600 dark:text-gray-300">{q ? `Nothing skipped matches “${search.trim()}”` : EMPTY.skipped}</p>
    {/if}
  {:else}
    <table class="w-full text-left text-sm">
      <thead class="hidden sm:table-header-group">
        <tr class={HEAD_ROW}>
          <!-- pl-11: the label lines up with the titles, past the status icon -->
          <th scope="col" class="{TH} pl-11">Title</th>
          <th scope="col" class={TH}>Status</th>
          <th scope="col" class="{TH} pr-3 text-right">When</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200 dark:divide-gray-800">
        {#each shownJobs as j (j.id)}
          {@const reason = reasonFor(j)}
          {@const kind = jobIcon(j.status, !!reason)}
          {@const problem = kind === 'warning' || kind === 'failed' ? reason : undefined}
          <tr
            class="cursor-pointer transition-colors duration-150 hover:bg-gray-100 dark:hover:bg-gray-800/50 focus-visible:bg-gray-100 dark:focus-visible:bg-gray-800/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-500 {arrived[j.id] ? 'arrived' : ''}"
            tabindex="0"
            onclick={() => openJob(j.id)}
            onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), openJob(j.id))}
          >
            <!-- max-w-0 + w-full: the title takes the spare width and truncates instead of widening the table. -->
            <td class="w-full max-w-0 min-w-32 py-3.5 pr-4 pl-3">
              <!-- icon shares the title's flex row so it sits on the title line, not the middle of the whole cell -->
              <div class="flex items-start gap-3">
                <StatusIcon {kind} tip={problem} draw={!!arrived[j.id]} />
                <div class="min-w-0 flex-1">
                  <div class="truncate font-medium text-gray-900 dark:text-gray-100" title={j.title ?? ''}>{j.title ?? '—'}</div>
                  <!-- Only trouble earns a second line; everything else about the job is in the drawer. -->
                  {#if problem}
                    <div
                      class="mt-0.5 truncate text-xs font-normal {kind === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'}"
                      title={problem}
                    >
                      {problem}
                    </div>
                  {/if}
                  <!-- Phones: the track is too wide for its own column, so it sits under the title. -->
                  <div class="mt-2 sm:hidden">{@render steps(j)}</div>
                </div>
              </div>
            </td>
            <td class="hidden px-4 py-3.5 sm:table-cell">{@render steps(j)}</td>
            <td class="hidden py-3.5 pr-3 pl-4 text-right whitespace-nowrap text-gray-500 dark:text-gray-400 tabular-nums sm:table-cell">{ago(j.created_at)}</td>
          </tr>
        {:else}
          {#if !loaded}
            {#each [0, 1, 2] as _}
              <tr>
                <td class="py-3.5 pr-4 pl-3">
                  <div class="flex items-center gap-3">
                    <div class="h-5 w-5 shrink-0 animate-pulse rounded-full bg-gray-200 dark:bg-gray-800"></div>
                    <div class="h-3.5 w-2/3 animate-pulse rounded bg-gray-200 dark:bg-gray-800"></div>
                  </div>
                </td>
                <td class="hidden px-4 py-3.5 sm:table-cell"><div class="h-2.5 w-62 animate-pulse rounded-full bg-gray-200 dark:bg-gray-800"></div></td>
                <td class="hidden py-3.5 pr-3 pl-4 sm:table-cell"><div class="ml-auto h-3 w-12 animate-pulse rounded bg-gray-200 dark:bg-gray-800"></div></td>
              </tr>
            {/each}
          {/if}
        {/each}
      </tbody>
    </table>
    {#if loaded && !shownJobs.length}
      <div class="py-10 text-center">
        <p class="text-gray-600 dark:text-gray-300">{q ? `No transfers match “${search.trim()}”` : EMPTY[filter]}</p>
        {#if !q && filter === 'all' && !sources.length}
          <p class="mt-1 text-sm text-gray-500">
            Transfers show up here once a <a href="/sources/" class="text-primary-400 underline-offset-2 hover:underline">source</a> finds something to fetch.
          </p>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<JobDrawer jobId={drawerJob} bind:open={drawerOpen} onchanged={load} />

<style>
  /* A job that finished while you watched: a green wash that settles back into the table. */
  :global(tr.arrived) {
    animation: arrived 2.2s cubic-bezier(0.16, 1, 0.3, 1);
  }
  @keyframes arrived {
    from {
      background-color: rgb(34 197 94 / 0.16);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    :global(tr.arrived) {
      animation: none;
    }
  }
</style>

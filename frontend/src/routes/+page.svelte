<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button, ButtonGroup, Input, Table, TableHead, TableHeadCell, TableBody, TableBodyRow, TableBodyCell, Alert } from 'flowbite-svelte';
  import { endpoints, type Job } from '$lib/api/client';
  import { STATUS_GROUPS, jobIcon, ago } from '$lib/status';
  import { jobSteps, reasonFor } from '$lib/pipeline';
  import StatusIcon from '$lib/components/StatusIcon.svelte';
  import StepDots from '$lib/components/steps/StepDots.svelte';
  import StatCards from '$lib/components/StatCards.svelte';
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
  let drawerOpen = $state(false);
  let drawerJob = $state<string | null>(null);

  const sum = (by: Record<string, number>, g: 'active' | 'failed') =>
    STATUS_GROUPS[g].reduce((n, s) => n + (by[s] ?? 0), 0);
  const by = $derived(dash?.jobs?.by_status ?? {});
  const q = $derived(search.trim().toLowerCase());
  const shownJobs = $derived(jobs.filter((j) => !q || (j.title ?? '').toLowerCase().includes(q)));
  const shownSkipped = $derived(skipped.filter((i) => !q || (i.title ?? '').toLowerCase().includes(q)));

  async function load() {
    const f = filter;
    try {
      const [d, list] = await Promise.all([
        endpoints.dashboard.get(),
        f === 'skipped'
          ? endpoints.sourceItems.skipped({ limit: 100 })
          : endpoints.jobs.list({
              limit: 100,
              ...(f === 'all'
                ? { sort: 'attention' as const }
                : { status: STATUS_GROUPS[f] }),
            }),
      ]);
      if (f !== filter) return; // filter changed while loading
      dash = d;
      if (f === 'skipped') skipped = list.items;
      else jobs = list.items as Job[];
      error = '';
    } catch (e: any) {
      error = e.message;
    }
  }

  // Reload on filter change; afterwards the server's event stream says when jobs changed.
  $effect(() => {
    filter;
    jobs = [];
    skipped = [];
    load();
  });

  // Live updates over SSE: progress for running jobs, and a jobs version that changes on any
  // create/update/delete, so the list reloads only when something actually changed.
  $effect(() => {
    let version: string | undefined;
    const es = new EventSource('/api/v1/events');
    es.addEventListener('snapshot', (ev) => {
      try {
        const snap = JSON.parse((ev as MessageEvent).data);
        const next: Record<string, { stage: string; pct: number }> = {};
        for (const j of snap.jobs)
          if (j.progress != null) next[j.id] = { stage: j.stage, pct: j.progress };
        progress = next;
        if (version !== undefined && snap.version !== version) load();
        version = snap.version;
      } catch {
        /* ignore malformed snapshot */
      }
    });
    return () => es.close();
  });

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

<div class="space-y-4">
  <StatCards
    active={sum(by, 'active')}
    failed={sum(by, 'failed')}
    done7d={dash?.jobs?.completed_7d ?? 0}
  />

  <div class="flex flex-wrap items-center justify-between gap-2">
    <ButtonGroup>
      {#each FILTERS as x}
        <Button color={filter === x ? 'primary' : 'alternative'} onclick={() => setFilter(x)} class="capitalize">{x}</Button>
      {/each}
    </ButtonGroup>
    <Input type="search" placeholder="Filter by title" bind:value={search} class="max-w-xs" />
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#if filter === 'skipped'}
    <Table hoverable>
      <TableHead>
        <TableHeadCell>Title</TableHeadCell>
        <TableHeadCell>Source / label</TableHeadCell>
        <TableHeadCell>Reason</TableHeadCell>
        <TableHeadCell></TableHeadCell>
      </TableHead>
      <TableBody>
        {#each shownSkipped as i (i.id)}
          <TableBodyRow>
            <TableBodyCell class="whitespace-normal break-words">{i.title ?? '—'}</TableBodyCell>
            <TableBodyCell>{i.source_name ?? i.source_id} · {(i.labels ?? []).join(', ') || '—'}</TableBodyCell>
            <TableBodyCell>Already in library</TableBodyCell>
            <TableBodyCell><Button size="xs" onclick={() => fetchAnyway(i.id)}>Fetch anyway</Button></TableBodyCell>
          </TableBodyRow>
        {/each}
      </TableBody>
    </Table>
    {#if !shownSkipped.length}<p class="py-8 text-center text-gray-500">{EMPTY.skipped}</p>{/if}
  {:else}
    <Table hoverable>
      <TableHead>
        <TableHeadCell class="w-8"></TableHeadCell>
        <TableHeadCell>Title</TableHeadCell>
        <TableHeadCell>Route</TableHeadCell>
        <TableHeadCell>Status</TableHeadCell>
        <TableHeadCell>When</TableHeadCell>
      </TableHead>
      <TableBody>
        {#each shownJobs as j (j.id)}
          {@const reason = reasonFor(j)}
          {@const kind = jobIcon(j.status, !!reason)}
          <TableBodyRow class="cursor-pointer" onclick={() => openJob(j.id)}>
            <TableBodyCell
              ><StatusIcon {kind} tip={kind === 'warning' || kind === 'failed' ? reason : undefined} /></TableBodyCell
            >
            {@const route = `${j.config_snapshot?.source_name ?? '—'} · ${j.config_snapshot?.label ?? '—'} → ${j.library_name ?? '—'}`}
            <TableBodyCell class="font-medium">
              <div class="max-w-xs truncate" title={j.title ?? ''}>{j.title ?? '—'}</div>
            </TableBodyCell>
            <TableBodyCell>
              <div class="max-w-xs truncate" title={route}>{route}</div>
            </TableBodyCell>
            <TableBodyCell>
              <StepDots steps={jobSteps(j, progress[j.id]?.stage === j.stage ? progress[j.id].pct : undefined)} />
            </TableBodyCell>
            <TableBodyCell>{ago(j.ended_at ?? j.created_at)}</TableBodyCell>
          </TableBodyRow>
        {/each}
      </TableBody>
    </Table>
    {#if !shownJobs.length}<p class="py-8 text-center text-gray-500">{EMPTY[filter]}</p>{/if}
  {/if}
</div>

<JobDrawer jobId={drawerJob} bind:open={drawerOpen} onchanged={load} />

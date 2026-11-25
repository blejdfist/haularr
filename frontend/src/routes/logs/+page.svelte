<script lang="ts">
  import { onMount } from 'svelte';
  import { Alert, Spinner } from 'flowbite-svelte';
  import { RefreshOutline, SearchOutline } from 'flowbite-svelte-icons';
  import { endpoints, type LogEntry } from '$lib/api/client';
  import { subscribe } from '$lib/live';

  // Minimum level: each tab shows that level and everything above it.
  const LEVELS = [
    ['all', 'All'],
    ['INFO', 'Info & up'],
    ['WARNING', 'Warnings & up'],
    ['ERROR', 'Errors'],
  ] as const;
  // Column widths shared by the header and the rows (from sm up).
  const COLS = 'sm:grid-cols-[7.5rem_5.5rem_minmax(0,13rem)_minmax(0,1fr)]';

  function setLevel(next: string) {
    level = next;
    load();
  }

  let level = $state<string>('all');
  let search = $state('');
  let entries = $state<LogEntry[]>([]);
  let total = $state(0);
  let capacity = $state(0);
  let names = $state<Record<string, string>>({});
  let loading = $state(true);
  let error = $state('');
  let autoRefresh = $state(true);

  const LIMIT = 500;
  // Filters of the last fetch; the stream sends only entries matching them.
  let applied = $state({ level: undefined as string | undefined, search: undefined as string | undefined });

  async function load() {
    clearTimeout(typing);
    const f = { level: level === 'all' ? undefined : level, search: search.trim() || undefined };
    try {
      const data = await endpoints.logs.list({ ...f, limit: LIMIT });
      entries = data.entries;
      total = data.total;
      capacity = data.capacity;
      names = data.names ?? {};
      error = '';
      if (f.level !== applied.level || f.search !== applied.search) applied = f;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  // New entries arrive over the log stream while auto-refresh is on. Each (re)connect refetches,
  // so nothing logged while disconnected is missed; seq drops entries the fetch already had.
  $effect(() => {
    if (!autoRefresh) return;
    const q = new URLSearchParams();
    if (applied.level) q.set('level', applied.level);
    if (applied.search) q.set('search', applied.search);
    return subscribe(`/events/logs?${q}`, {
      open: load,
      log: (d: { entries: LogEntry[]; names: Record<string, string> }) => {
        const newest = entries[0]?.seq ?? 0;
        const fresh = d.entries.filter((e) => e.seq > newest).reverse();
        if (!fresh.length) return;
        entries = [...fresh, ...entries].slice(0, LIMIT);
        total = Math.min(total + fresh.length, capacity || Infinity);
        names = { ...names, ...d.names };
      },
    });
  });

  // Search as you type, once typing pauses; Enter searches right away.
  let typing: ReturnType<typeof setTimeout>;
  function onType() {
    clearTimeout(typing);
    typing = setTimeout(load, 300);
  }
  function onSearch(e: Event) {
    e.preventDefault();
    load();
  }

  const LEVEL_TEXT: Record<string, string> = {
    DEBUG: 'text-gray-500',
    INFO: 'text-sky-600 dark:text-sky-400',
    WARNING: 'text-amber-600 dark:text-amber-400',
    ERROR: 'text-red-600 dark:text-red-400',
    CRITICAL: 'text-red-600 dark:text-red-400',
  };
  const isError = (l: string) => l === 'ERROR' || l === 'CRITICAL';

  // Ids in a message show as highlighted names (id in the tooltip): either `"Name" (id)` as the
  // backend writes it, or a bare id the server resolved in `names`.
  const TOKEN =
    /"([^"]*)" \(([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)|([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g;

  function segments(msg: string): { text: string; id?: string }[] {
    const out: { text: string; id?: string }[] = [];
    let last = 0;
    for (const m of msg.matchAll(TOKEN)) {
      if (m.index > last) out.push({ text: msg.slice(last, m.index) });
      const id = m[2] ?? m[3];
      const name = m[1] ?? names[id];
      out.push(name ? { text: name, id } : { text: m[0] });
      last = m.index + m[0].length;
    }
    if (last < msg.length) out.push({ text: msg.slice(last) });
    return out;
  }

  // Rows show the time only; a sticky header above each day's entries carries the date.
  const fmtTime = (s: string) =>
    new Date(s).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dayOf = (s: string) => new Date(s).toDateString();
  function dayLabel(s: string): string {
    const d = new Date(s);
    const today = new Date();
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
  }
</script>

<!-- Fill the viewport below the page padding (and the mobile top bar) so the list scrolls, not the page. -->
<div class="flex h-[calc(100dvh-5.6rem)] flex-col gap-5 lg:h-[calc(100dvh-3rem)]">
  <header class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
    <div>
      <h1 class="text-2xl font-bold">Application logs</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
        Recent log entries captured in memory{#if capacity}<span class="text-gray-500 tabular-nums"
            >&nbsp;· {total} of {capacity} buffered</span
          >{/if}
      </p>
    </div>
    <div class="-mx-3 flex items-center gap-1">
      {#if !autoRefresh}
        <button
          type="button"
          onclick={load}
          class="rounded-lg p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:outline-none"
          title="Refresh now"
        >
          <RefreshOutline class="h-4 w-4" />
          <span class="sr-only">Refresh now</span>
        </button>
      {/if}
      <button
        type="button"
        aria-pressed={autoRefresh}
        onclick={() => (autoRefresh = !autoRefresh)}
        title={autoRefresh ? 'New entries appear as they are logged. Click to pause.' : 'Paused. Click to follow new entries.'}
        class="inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:outline-none"
      >
        <span class="relative flex h-2 w-2">
          {#if autoRefresh}<span class="absolute inset-0 animate-ping rounded-full bg-green-500 opacity-60 motion-reduce:hidden"></span>{/if}
          <span class="relative h-2 w-2 rounded-full {autoRefresh ? 'bg-green-500' : 'bg-gray-500'}"></span>
        </span>
        {autoRefresh ? 'Live' : 'Paused'}
      </button>
    </div>
  </header>

  <!-- Same filter bar as the dashboard: tabs on the shared underline, search on the right. -->
  <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-3 border-b border-gray-200 dark:border-gray-700">
    <nav class="-mb-px flex max-w-full [scrollbar-width:none] overflow-x-auto" aria-label="Minimum log level">
      {#each LEVELS as [value, label]}
        <button
          type="button"
          aria-pressed={level === value}
          onclick={() => setLevel(value)}
          class="border-b-2 px-3 pt-1 pb-3 text-sm font-medium whitespace-nowrap transition-colors duration-150 focus-visible:bg-gray-800 focus-visible:outline-none {level ===
          value
            ? 'border-primary-500 text-gray-900 dark:text-white'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:border-gray-400 hover:text-gray-700 dark:hover:border-gray-500 dark:hover:text-gray-200'}"
        >
          {label}
        </button>
      {/each}
    </nav>
    <form onsubmit={onSearch} class="relative mb-2.5 w-full sm:w-64">
      <label>
        <span class="sr-only">Filter logs</span>
        <SearchOutline class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-500" />
        <input
          type="search"
          placeholder="Filter logs"
          bind:value={search}
          oninput={onType}
          class="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white py-2 pr-3 pl-9 text-sm text-gray-900 dark:bg-gray-800 dark:text-white placeholder:text-gray-400 focus:border-primary-500 focus:ring-primary-500"
        />
      </label>
    </form>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  <!-- The list scrolls inside the page; rows sit on the page like the dashboard's job list. -->
  <div class="-mt-5 min-h-0 flex-1 overflow-auto text-sm">
    {#if loading}
      <div class="flex h-full items-center justify-center"><Spinner size="6" /></div>
    {:else if !entries.length}
      <p class="py-10 text-center text-gray-600 dark:text-gray-300">
        {search.trim() || level !== 'all' ? 'No log entries match the current filters.' : 'Nothing logged yet.'}
      </p>
    {:else}
      <div class="sticky top-0 z-10 hidden border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 pt-5 text-xs font-medium text-gray-500 dark:text-gray-400 sm:grid {COLS}">
        <span class="pb-2.5 pl-3">Time</span>
        <span class="pb-2.5">Level</span>
        <span class="pb-2.5">Source</span>
        <span class="pr-3 pb-2.5">Message</span>
      </div>
      {#each entries as e, i (e.seq)}
        {#if i === 0 || dayOf(e.timestamp) !== dayOf(entries[i - 1].timestamp)}
          <div class="border-b border-gray-200 dark:border-gray-800 px-3 pb-2 text-xs font-medium text-gray-500 {i === 0 ? 'pt-5 sm:pt-3' : 'pt-4'}">
            {dayLabel(e.timestamp)}
          </div>
        {/if}
        <!-- Phones: time, level and source on one line, the message full width below. Wider: four aligned columns. -->
        <div
          class="grid grid-cols-[auto_auto_minmax(0,1fr)] gap-x-2.5 gap-y-1 border-b sm:gap-x-0 border-gray-200 dark:border-gray-800 py-2.5 transition-colors duration-150 hover:bg-gray-100 dark:hover:bg-gray-800/50 {COLS}"
        >
          <span class="pl-3 text-gray-500 dark:text-gray-400 tabular-nums">{fmtTime(e.timestamp)}</span>
          <span class="text-xs leading-5 font-semibold tracking-wide {LEVEL_TEXT[e.level] ?? 'text-gray-500 dark:text-gray-400'}">{e.level}</span>
          <span class="truncate pr-3 text-gray-500 dark:text-gray-400 sm:pr-4" title={e.logger}>{e.logger}</span>
          <span
            class="col-span-full px-3 [overflow-wrap:anywhere] sm:col-span-1 sm:pl-0 {isError(e.level)
              ? 'text-red-700 dark:text-red-300'
              : e.level === 'DEBUG'
                ? 'text-gray-500 dark:text-gray-400'
                : 'text-gray-900 dark:text-gray-100'}"
            >{#each segments(e.message) as seg}{#if seg.id}<span class="font-medium text-primary-400" title={seg.id}
                  >{seg.text}</span
                >{:else}{seg.text}{/if}{/each}</span
          >
          {#if e.exception}
            <details class="col-span-full px-3 sm:col-start-4 sm:pl-0">
              <summary class="cursor-pointer text-xs text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300">Show traceback</summary>
              <pre class="mt-1.5 overflow-auto rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-100 dark:bg-gray-950 p-3 font-mono text-xs text-red-700 dark:text-red-300">{e.exception}</pre>
            </details>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>

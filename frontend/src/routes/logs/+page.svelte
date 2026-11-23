<script lang="ts">
  import { onMount } from 'svelte';
  import { Alert, Badge, Button, Input, Spinner } from 'flowbite-svelte';
  import { endpoints, type LogEntry } from '$lib/api/client';

  const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const;

  let level = $state<string>('all');
  let search = $state('');
  let entries = $state<LogEntry[]>([]);
  let total = $state(0);
  let capacity = $state(0);
  let loading = $state(true);
  let error = $state('');
  let autoRefresh = $state(true);

  async function load() {
    try {
      const data = await endpoints.logs.list({
        level: level === 'all' ? undefined : level,
        search: search.trim() || undefined,
        limit: 500,
      });
      entries = data.entries;
      total = data.total;
      capacity = data.capacity;
      error = '';
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  // Poll for new logs while auto-refresh is on.
  $effect(() => {
    if (!autoRefresh) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  });

  function onSearch(e: Event) {
    e.preventDefault();
    load();
  }

  function levelColor(l: string): 'blue' | 'red' | 'yellow' | 'green' | 'gray' {
    if (l === 'ERROR' || l === 'CRITICAL') return 'red';
    if (l === 'WARNING') return 'yellow';
    if (l === 'INFO') return 'blue';
    return 'gray';
  }

  function fmtTime(s: string): string {
    const d = new Date(s);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    return sameDay ? d.toLocaleTimeString() : `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
  }
</script>

<div class="space-y-4">
  <div class="flex flex-wrap items-end justify-between gap-2">
    <div>
      <h1 class="text-2xl font-bold">Application logs</h1>
      <p class="text-sm text-gray-500">
        Recent log entries captured in memory{#if capacity}
          ({total} of {capacity} buffered){/if}
      </p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <select
        bind:value={level}
        onchange={load}
        class="rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
        aria-label="Minimum log level"
      >
        <option value="all">All levels</option>
        {#each LEVELS as l}
          <option value={l}>{l}</option>
        {/each}
      </select>
      <form onsubmit={onSearch} class="flex gap-2">
        <Input type="search" placeholder="Filter logs" bind:value={search} class="w-48" />
        <Button type="submit">Search</Button>
      </form>
      <Button
        type="button"
        color={autoRefresh ? 'primary' : 'alternative'}
        onclick={() => (autoRefresh = !autoRefresh)}
        title="Toggle auto-refresh"
      >
        Auto-refresh: {autoRefresh ? 'on' : 'off'}
      </Button>
      <Button type="button" color="alternative" onclick={load}>Refresh</Button>
    </div>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#if loading}
    <Spinner />
  {:else if !entries.length}
    <p class="py-8 text-center text-gray-500">No log entries match the current filters.</p>
  {:else}
    <div
      class="max-h-[70vh] overflow-auto rounded-lg border border-gray-200 bg-white font-mono text-sm dark:border-gray-700 dark:bg-gray-800"
    >
      {#each entries as e (e.timestamp + e.message)}
        <div
          class="border-b border-gray-100 px-3 py-1.5 last:border-0 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-700/50"
        >
          <div class="flex items-start gap-3">
            <span class="shrink-0 text-gray-400">{fmtTime(e.timestamp)}</span>
            <span class="shrink-0">
              <Badge color={levelColor(e.level)} class="font-mono">{e.level}</Badge>
            </span>
            <span class="shrink-0 truncate text-gray-400" title={e.logger}>{e.logger}</span>
            <span class="break-all">{e.message}</span>
          </div>
          {#if e.exception}
            <details class="mt-1 pl-[7.75rem]">
              <summary class="cursor-pointer text-xs text-red-400 hover:text-red-300">
                Show traceback
              </summary>
              <pre class="mt-1 overflow-auto rounded bg-gray-900 p-2 text-xs text-red-300">{e.exception}</pre>
            </details>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

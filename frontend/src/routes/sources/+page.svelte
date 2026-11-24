<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Alert, Spinner } from 'flowbite-svelte';
  import { endpoints, type Source, type Library } from '$lib/api/client';
  import { sourceHealth, ago } from '$lib/status';
  import SourceEditor from '$lib/components/SourceEditor.svelte';
  import EntityCard from '$lib/components/EntityCard.svelte';

  let sources = $state<Source[]>([]);
  let libraries = $state<Library[]>([]);
  let tagCounts = $state<Record<string, number>>({});
  let loaded = $state(false);
  let error = $state('');
  let open = $state(false);
  let editing = $state<Source | null>(null);
  let scanning = $state(false);

  async function load() {
    try {
      [sources, libraries] = await Promise.all([endpoints.sources.list(), endpoints.libraries.list()]);
      const counts = await Promise.all(sources.map((s) => endpoints.sources.labels.list(s.id)));
      tagCounts = Object.fromEntries(sources.map((s, i) => [s.id, counts[i].length]));
      error = '';
    } catch (e: any) {
      error = e.message;
    }
    loaded = true;
  }
  onMount(load);

  function edit(s: Source | null) {
    editing = s;
    open = true;
  }

  async function scanAll() {
    scanning = true;
    try {
      await Promise.all(sources.filter((s) => s.enabled).map((s) => endpoints.sources.scan(s.id)));
      // Scans run in the background; refresh once they have had a moment.
      await new Promise((r) => setTimeout(r, 1500));
      await load();
    } catch (e: any) {
      error = e.message;
    } finally {
      scanning = false;
    }
  }

  const HEALTH = {
    ok: 'Last scan OK',
    error: 'Last scan failed',
    never: 'Not scanned yet',
  } as const;
  const TYPES: Record<string, string> = { rtorrent: 'rTorrent' };
</script>

<div class="space-y-4">
  <div class="flex items-center justify-between gap-2">
    <h1 class="text-2xl font-bold">Sources</h1>
    <div class="flex gap-2">
      <Button color="alternative" disabled={scanning || !sources.some((s) => s.enabled)} onclick={scanAll}>
        {#if scanning}<Spinner size="4" class="me-2" />{/if}Scan all
      </Button>
      <Button onclick={() => edit(null)}>Add source</Button>
    </div>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}
  {#if loaded && !sources.length && !error}
    <p class="text-gray-500 dark:text-gray-400">No sources yet. Add an rTorrent instance.</p>
  {/if}

  <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
    {#each sources as s (s.id)}
      {@const h = sourceHealth(s)}
      <EntityCard
        name={s.name}
        dot={h}
        dotText={HEALTH[h]}
        badge={TYPES[s.adapter_type] ?? s.adapter_type}
        badgeColor="purple"
        onclick={() => edit(s)}
      >
        {#if !s.enabled}Disabled ·{/if}
        Last scan: {s.last_scan_at ? ago(s.last_scan_at) : 'never'} · {tagCounts[s.id] ?? 0}
        {tagCounts[s.id] === 1 ? 'tag' : 'tags'}
      </EntityCard>
    {/each}
  </div>
</div>

<SourceEditor bind:open source={editing} {libraries} onsaved={load} ondeleted={load} />

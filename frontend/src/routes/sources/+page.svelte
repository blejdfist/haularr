<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Card, Badge, Alert } from 'flowbite-svelte';
  import { endpoints, type Source, type Library } from '$lib/api/client';
  import { sourceHealth, ago } from '$lib/status';
  import SourceEditor from '$lib/components/SourceEditor.svelte';

  let sources = $state<Source[]>([]);
  let libraries = $state<Library[]>([]);
  let tagCounts = $state<Record<string, number>>({});
  let loaded = $state(false);
  let error = $state('');
  let open = $state(false);
  let editing = $state<Source | null>(null);

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

  const HEALTH = {
    ok: { color: 'green', text: 'OK' },
    error: { color: 'red', text: 'Error' },
    never: { color: 'gray', text: 'Not scanned' },
  } as const;
</script>

<div class="space-y-4">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">Sources</h1>
    <Button onclick={() => edit(null)}>Add source</Button>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}
  {#if loaded && !sources.length && !error}
    <p class="text-gray-500 dark:text-gray-400">No sources yet. Add an rTorrent instance.</p>
  {/if}

  <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
    {#each sources as s (s.id)}
      {@const h = HEALTH[sourceHealth(s)]}
      <Card class="max-w-none cursor-pointer space-y-2 p-4" onclick={() => edit(s)}>
        <div class="flex items-center justify-between gap-2">
          <h2 class="truncate text-lg font-semibold">{s.name}</h2>
          <Badge color={h.color}>{h.text}</Badge>
        </div>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Last scan: {s.last_scan_at ? ago(s.last_scan_at) : 'never'} · {tagCounts[s.id] ?? 0} {tagCounts[s.id] === 1 ? 'tag' : 'tags'}
          {#if !s.enabled}· disabled{/if}
        </p>
      </Card>
    {/each}
  </div>
</div>

<SourceEditor bind:open source={editing} {libraries} onsaved={load} ondeleted={load} />

<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Alert } from 'flowbite-svelte';
  import { endpoints, type Library } from '$lib/api/client';
  import LibraryModal from '$lib/components/LibraryModal.svelte';
  import EntityCard from '$lib/components/EntityCard.svelte';
  import type { Dot } from '$lib/status';

  let libraries = $state<Library[]>([]);
  let loaded = $state(false);
  let error = $state('');
  let modalOpen = $state(false);
  let editing = $state<Library | null>(null);
  let health = $state<Record<string, { dot: Dot; text: string }>>({});

  async function load() {
    try {
      libraries = await endpoints.libraries.list();
      error = '';
    } catch (e: any) {
      error = e.message;
    }
    loaded = true;
    // One connection check per library per page view: feeds the status dot.
    for (const l of libraries) {
      health[l.id] = { dot: 'checking', text: 'Checking…' };
      endpoints.libraries
        .test(l.id)
        .then((r) => (health[l.id] = r.ok ? { dot: 'ok', text: `Connected${r.version ? ` (v${r.version})` : ''}` } : { dot: 'error', text: r.error ?? 'Connection failed' }))
        .catch((e) => (health[l.id] = { dot: 'error', text: e.message }));
    }
  }
  onMount(load);

  function edit(l: Library | null) {
    editing = l;
    modalOpen = true;
  }
</script>

<div class="space-y-4">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">Libraries</h1>
    <Button onclick={() => edit(null)}>Add library</Button>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#if loaded && !libraries.length && !error}
    <p class="text-gray-500 dark:text-gray-400">No libraries yet. Add a Sonarr or Radarr instance.</p>
  {/if}

  <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
    {#each libraries as l (l.id)}
      {@const h = health[l.id] ?? { dot: 'checking', text: 'Checking…' }}
      <EntityCard
        name={l.name}
        dot={h.dot}
        dotText={h.text}
        badge={l.adapter_type === 'sonarr' ? 'Sonarr' : 'Radarr'}
        badgeColor={l.adapter_type === 'sonarr' ? 'blue' : 'yellow'}
        onclick={() => edit(l)}
      >
        {h.dot === 'error' ? h.text : l.base_url}
      </EntityCard>
    {/each}
  </div>
</div>

<LibraryModal bind:open={modalOpen} library={editing} onsaved={load} ondeleted={load} />

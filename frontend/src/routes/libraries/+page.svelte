<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Card, Badge, Alert, Modal } from 'flowbite-svelte';
  import { endpoints, type Library } from '$lib/api/client';
  import LibraryModal from '$lib/components/LibraryModal.svelte';

  let libraries = $state<Library[]>([]);
  let loaded = $state(false);
  let error = $state('');
  let modalOpen = $state(false);
  let editing = $state<Library | null>(null);
  let deleting = $state<Library | null>(null);
  let confirmOpen = $state(false);
  let results = $state<Record<string, { ok: boolean; text: string; pending?: boolean }>>({});

  async function load() {
    try {
      libraries = await endpoints.libraries.list();
      error = '';
    } catch (e: any) {
      error = e.message;
    }
    loaded = true;
  }
  onMount(load);

  function edit(l: Library | null) {
    editing = l;
    modalOpen = true;
  }

  async function test(l: Library) {
    results[l.id] = { ok: true, text: 'Testing...', pending: true };
    try {
      const r = await endpoints.libraries.test(l.id);
      results[l.id] = r.ok
        ? { ok: true, text: `Connected${r.version ? ' (v' + r.version + ')' : ''}` }
        : { ok: false, text: r.error ?? 'Connection failed' };
    } catch (e: any) {
      results[l.id] = { ok: false, text: e.message };
    }
  }

  async function remove() {
    if (!deleting) return;
    try {
      await endpoints.libraries.delete(deleting.id);
      delete results[deleting.id];
      error = '';
    } catch (e: any) {
      error = e.message;
    }
    confirmOpen = false;
    deleting = null;
    load();
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
      <Card class="max-w-none space-y-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h2 class="truncate text-lg font-semibold">{l.name}</h2>
          <Badge color={l.adapter_type === 'sonarr' ? 'blue' : 'yellow'}>
            {l.adapter_type === 'sonarr' ? 'Sonarr' : 'Radarr'}
          </Badge>
        </div>
        <p class="truncate text-sm text-gray-500 dark:text-gray-400">{l.base_url}</p>
        {#if results[l.id]}
          <p class="text-sm {results[l.id].pending ? 'text-gray-500' : results[l.id].ok ? 'text-green-500' : 'text-red-500'}">{results[l.id].text}</p>
        {/if}
        <div class="flex flex-wrap gap-2">
          {#if /^https?:\/\//i.test(l.base_url)}
            <Button size="xs" color="alternative" href={l.base_url} target="_blank" rel="noopener noreferrer">Open</Button>
          {/if}
          <Button size="xs" color="alternative" onclick={() => test(l)}>Test</Button>
          <Button size="xs" color="alternative" onclick={() => edit(l)}>Edit</Button>
          <Button
            size="xs"
            color="red"
            onclick={() => {
              deleting = l;
              confirmOpen = true;
            }}>Delete</Button
          >
        </div>
      </Card>
    {/each}
  </div>
</div>

<LibraryModal bind:open={modalOpen} library={editing} onsaved={() => { if (editing) delete results[editing.id]; load(); }} />

<Modal bind:open={confirmOpen} title="Delete library" size="xs">
  <p>Delete <strong>{deleting?.name}</strong>? This cannot be undone.</p>
  <div class="mt-4 flex justify-end gap-2">
    <Button color="alternative" onclick={() => (confirmOpen = false)}>Cancel</Button>
    <Button color="red" onclick={remove}>Delete</Button>
  </div>
</Modal>

<script lang="ts">
  import { Card, Button, Spinner } from 'flowbite-svelte';
  import { RefreshOutline } from 'flowbite-svelte-icons';
  import { endpoints } from '$lib/api/client';
  import type { Health } from '$lib/status';

  let { active, failed, done7d, sources, onscanned }: {
    active: number;
    failed: number;
    done7d: number;
    sources: { id: string; name: string; health: Health }[];
    onscanned?: () => void;
  } = $props();

  const dot = { ok: 'bg-green-500', error: 'bg-red-500', never: 'bg-gray-400' } as const;
  let scanning = $state<Record<string, boolean>>({});
  let scanError = $state('');
  const anyScanning = $derived(Object.values(scanning).some(Boolean));

  async function scan(ids: string[]) {
    scanError = '';
    for (const id of ids) scanning[id] = true;
    try {
      await Promise.all(ids.map((id) => endpoints.sources.scan(id)));
      // Scans run in the background; refresh once they have had a moment.
      await new Promise((r) => setTimeout(r, 1500));
      onscanned?.();
    } catch (e: any) {
      scanError = e.message;
    } finally {
      for (const id of ids) scanning[id] = false;
    }
  }
</script>

<div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
  <Card class="p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Active</div>
    <div class="text-3xl font-bold text-blue-600 dark:text-blue-400">{active}</div>
  </Card>
  <Card class="p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Failed</div>
    <div class="text-3xl font-bold {failed ? 'text-red-600 dark:text-red-400' : ''}">{failed}</div>
  </Card>
  <Card class="p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Completed (7d)</div>
    <div class="text-3xl font-bold">{done7d}</div>
  </Card>
  <Card class="p-4">
    <div class="flex items-center justify-between gap-2">
      <div class="text-sm text-gray-500 dark:text-gray-400">Sources</div>
      <Button
        size="xs"
        color="alternative"
        disabled={!sources.length || anyScanning}
        onclick={() => scan(sources.map((s) => s.id))}
      >
        {#if anyScanning}<Spinner size="4" class="me-1" />{/if}Scan all
      </Button>
    </div>
    <ul class="mt-2 space-y-1 text-sm">
      {#each sources as s (s.id)}
        <li class="flex items-center gap-2" title={s.health}>
          <span class="inline-block h-2.5 w-2.5 shrink-0 rounded-full {dot[s.health]}"></span>
          <span class="min-w-0 flex-1 truncate">{s.name}</span>
          <button
            class="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-50"
            aria-label="Scan {s.name}"
            title="Scan now"
            disabled={scanning[s.id]}
            onclick={() => scan([s.id])}
          >
            {#if scanning[s.id]}<Spinner size="4" />{:else}<RefreshOutline class="h-4 w-4" />{/if}
          </button>
        </li>
      {:else}
        <li class="text-gray-500">None</li>
      {/each}
    </ul>
    {#if scanError}<p class="mt-1 text-xs text-red-500">{scanError}</p>{/if}
  </Card>
</div>

<script lang="ts">
  import { Card } from 'flowbite-svelte';
  import type { Health } from '$lib/status';

  let { active, failed, done7d, sources }: {
    active: number;
    failed: number;
    done7d: number;
    sources: { name: string; health: Health }[];
  } = $props();

  const dot = { ok: 'bg-green-500', error: 'bg-red-500', never: 'bg-gray-400' } as const;
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
    <div class="text-sm text-gray-500 dark:text-gray-400">Sources</div>
    <ul class="mt-1 space-y-1 text-sm">
      {#each sources as s}
        <li class="flex items-center gap-2" title={s.health}>
          <span class="inline-block h-2.5 w-2.5 rounded-full {dot[s.health]}"></span>{s.name}
        </li>
      {:else}
        <li class="text-gray-500">None</li>
      {/each}
    </ul>
  </Card>
</div>

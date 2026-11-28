<script lang="ts">
  import { onMount } from 'svelte';
  import { Alert, Spinner } from 'flowbite-svelte';
  import { endpoints } from '$lib/api/client';

  let health = $state<Awaited<ReturnType<typeof endpoints.health>> | null>(null);
  let error = $state('');

  const cards = $derived(
    health
      ? [
          { label: 'Version', value: health.version },
          { label: 'Status', value: health.status === 'healthy' ? 'Healthy' : 'Degraded', ok: health.status === 'healthy' },
          { label: 'Database', value: health.database === 'ok' ? 'OK' : 'Error', ok: health.database === 'ok' },
        ]
      : [],
  );

  onMount(async () => {
    try {
      health = await endpoints.health();
    } catch (e) {
      error = (e as Error).message;
    }
  });
</script>

<h1 class="mb-4 text-2xl font-bold">System</h1>

{#if error}
  <Alert color="red">{error}</Alert>
{:else if !health}
  <Spinner />
{:else}
  <dl class="grid gap-4 sm:grid-cols-3">
    {#each cards as c}
      <div class="rounded-lg border border-gray-200 bg-white p-4 shadow-xs dark:border-gray-700 dark:bg-gray-800">
        <dt class="text-sm text-gray-500 dark:text-gray-400">{c.label}</dt>
        <dd class="mt-1 flex items-center gap-2 text-lg font-semibold tabular-nums text-gray-900 dark:text-white">
          {#if c.ok !== undefined}
            <span aria-hidden="true" class="h-2.5 w-2.5 shrink-0 rounded-full {c.ok ? 'bg-green-500' : 'bg-red-500'}"></span>
          {/if}
          {c.value}
        </dd>
      </div>
    {/each}
  </dl>
{/if}

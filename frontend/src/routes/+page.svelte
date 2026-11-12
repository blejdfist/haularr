<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let dashboard = $state<any>(null);
  let health = $state<any>(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      health = await endpoints.health();
      dashboard = await endpoints.dashboard.get();
    } catch (e) {
      console.error('Failed to load dashboard:', e);
    } finally {
      loading = false;
    }
  });
</script>

<div class="p-6">
  <h2 class="text-2xl font-bold mb-6">Dashboard</h2>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else}
    <!-- Health status -->
    <div class="mb-6 p-4 bg-slate-900 rounded-lg border border-slate-700">
      <div class="flex items-center gap-3">
        <div class="w-3 h-3 rounded-full {health?.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}"></div>
        <span class="text-sm text-slate-300">
          System: {health?.status ?? 'unknown'} · DB: {health?.database ?? 'unknown'} · v{health?.version ?? '?'}
        </span>
      </div>
    </div>

    <!-- Job stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {#if dashboard}
        {@const j = dashboard.jobs}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="text-3xl font-bold text-blue-400">{j.active}</div>
          <div class="text-sm text-slate-400">Active Jobs</div>
        </div>
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="text-3xl font-bold text-yellow-400">{j.queued}</div>
          <div class="text-sm text-slate-400">Queued</div>
        </div>
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="text-3xl font-bold text-orange-400">{j.needs_attention}</div>
          <div class="text-sm text-slate-400">Needs Attention</div>
        </div>
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="text-3xl font-bold text-green-400">{j.completed}</div>
          <div class="text-sm text-slate-400">Completed</div>
        </div>
      {/if}
    </div>

    <!-- Sources -->
    {#if dashboard?.sources}
      <div class="p-4 bg-slate-900 rounded-lg border border-slate-700 mb-6">
        <h3 class="text-lg font-semibold mb-3">Sources</h3>
        <div class="flex gap-4">
          {#each Object.entries(dashboard.sources) as [type, count]}
            <div class="px-3 py-2 bg-slate-800 rounded">
              <span class="text-sm text-slate-400">{type}:</span>
              <span class="ml-2 text-sm font-semibold">{count}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Capacity -->
    {#if dashboard?.capacity}
      <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <h3 class="text-lg font-semibold mb-3">Download Capacity</h3>
        <div class="flex items-center gap-4">
          <div class="text-sm text-slate-400">
            {dashboard.capacity.active_downloads} / {dashboard.capacity.max_concurrent_download_jobs} active downloads
          </div>
          <div class="flex-1 h-3 bg-slate-800 rounded-full overflow-hidden">
            <div
              class="h-full bg-blue-500 rounded-full transition-all"
              style="width: {(dashboard.capacity.active_downloads / dashboard.capacity.max_concurrent_download_jobs) * 100}%"
            ></div>
          </div>
        </div>
      </div>
    {/if}
  {/if}
</div>

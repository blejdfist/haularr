<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let jobs = $state<any[]>([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const data = await endpoints.jobs.list({ status: 'needs_attention' });
      jobs = data.items;
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<div class="p-6">
  <h2 class="text-2xl font-bold mb-6">Attention Queue</h2>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if jobs.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">
      No items need attention. Everything looks good!
    </div>
  {:else}
    <div class="grid gap-3">
      {#each jobs as job}
        <div class="p-4 bg-slate-900 rounded-lg border border-red-700">
          <div class="flex items-center gap-3 mb-2">
            <span class="text-red-400">⚠️</span>
            <span class="font-mono text-sm">{job.id}</span>
            <span class="text-red-400">{job.status}</span>
            <span class="px-2 py-0.5 text-xs bg-slate-700 rounded">{job.stage}</span>
          </div>
          {#if job.error_detail}
            <div class="text-sm text-red-300 ml-8">{job.error_detail}</div>
          {/if}
          {#if job.error_code}
            <div class="text-xs text-slate-500 ml-8 mt-1">Code: {job.error_code}</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let jobs = $state<any[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let filterStatus = $state('');

  async function load() {
    loading = true;
    try {
      const params: Record<string, string> = {};
      if (filterStatus) params.status = filterStatus;
      const data = await endpoints.jobs.list(params);
      jobs = data.items;
      total = data.total;
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function statusColor(status: string): string {
    const map: Record<string, string> = {
      queued: 'text-slate-400',
      running: 'text-blue-400',
      waiting_source: 'text-yellow-400',
      retry_wait: 'text-orange-400',
      paused: 'text-slate-500',
      needs_attention: 'text-red-400',
      failed: 'text-red-500',
      completed: 'text-green-400',
      cancelled: 'text-slate-600',
    };
    return map[status] ?? 'text-slate-400';
  }

  async function pauseJob(id: string) {
    await endpoints.jobs.pause(id);
    await load();
  }

  async function resumeJob(id: string) {
    await endpoints.jobs.resume(id);
    await load();
  }

  async function retryJob(id: string) {
    await endpoints.jobs.retry(id);
    await load();
  }

  async function cancelJob(id: string) {
    await endpoints.jobs.cancel(id);
    await load();
  }
</script>

<div class="p-6">
  <div class="flex justify-between items-center mb-6">
    <h2 class="text-2xl font-bold">Jobs</h2>
    <select bind:value={filterStatus} onchange={load} class="px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm">
      <option value="">All Statuses</option>
      <option value="queued">Queued</option>
      <option value="running">Running</option>
      <option value="waiting_source">Waiting Source</option>
      <option value="retry_wait">Retry Wait</option>
      <option value="paused">Paused</option>
      <option value="needs_attention">Needs Attention</option>
      <option value="failed">Failed</option>
      <option value="completed">Completed</option>
      <option value="cancelled">Cancelled</option>
    </select>
  </div>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if jobs.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">No jobs found.</div>
  {:else}
    <div class="grid gap-3">
      {#each jobs as job}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="flex justify-between items-start">
            <div>
              <div class="flex items-center gap-3">
                <span class="font-mono text-sm">{job.id}</span>
                <span class={statusColor(job.status)}>{job.status}</span>
                <span class="px-2 py-0.5 text-xs bg-slate-700 rounded">{job.stage}</span>
              </div>
              <div class="mt-2 text-sm text-slate-400">
                Source item: {job.source_item_id}
                {#if job.download_bytes_total > 0}
                  · {(job.download_bytes_done / 1e9).toFixed(2)} / {(job.download_bytes_total / 1e9).toFixed(2)} GB
                {/if}
                {#if job.error_detail}
                  · <span class="text-red-400">{job.error_detail}</span>
                {/if}
              </div>
            </div>
            <div class="flex gap-2">
              {#if job.status === 'running' || job.status === 'queued'}
                <button onclick={() => pauseJob(job.id)} class="px-2 py-1 text-xs bg-yellow-700 hover:bg-yellow-600 rounded">Pause</button>
              {/if}
              {#if job.status === 'paused'}
                <button onclick={() => resumeJob(job.id)} class="px-2 py-1 text-xs bg-green-700 hover:bg-green-600 rounded">Resume</button>
              {/if}
              {#if job.status === 'failed' || job.status === 'needs_attention'}
                <button onclick={() => retryJob(job.id)} class="px-2 py-1 text-xs bg-blue-700 hover:bg-blue-600 rounded">Retry</button>
              {/if}
              {#if job.status !== 'completed' && job.status !== 'cancelled'}
                <button onclick={() => cancelJob(job.id)} class="px-2 py-1 text-xs bg-red-700 hover:bg-red-600 rounded">Cancel</button>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
    <div class="mt-4 text-sm text-slate-400">Showing {jobs.length} of {total} jobs</div>
  {/if}
</div>

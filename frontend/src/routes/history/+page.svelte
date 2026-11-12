<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let jobs = $state<any[]>([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const data = await endpoints.jobs.list({});
      // Filter to terminal statuses
      const terminal = ['completed', 'failed', 'cancelled', 'completed_with_warnings', 'skipped'];
      jobs = data.items.filter((j: any) => terminal.includes(j.status));
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function statusColor(status: string): string {
    const map: Record<string, string> = {
      completed: 'text-green-400',
      failed: 'text-red-500',
      cancelled: 'text-slate-600',
      completed_with_warnings: 'text-yellow-400',
      skipped: 'text-slate-500',
    };
    return map[status] ?? 'text-slate-400';
  }
</script>

<div class="p-6">
  <h2 class="text-2xl font-bold mb-6">History</h2>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if jobs.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">No completed jobs in history.</div>
  {:else}
    <div class="grid gap-3">
      {#each jobs as job}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="flex justify-between">
            <div>
              <span class="font-mono text-sm">{job.id}</span>
              <span class="ml-2 {statusColor(job.status)}">{job.status}</span>
              <span class="ml-2 px-2 py-0.5 text-xs bg-slate-700 rounded">{job.stage}</span>
            </div>
            <div class="text-sm text-slate-400">
              {#if job.ended_at}
                {job.ended_at}
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

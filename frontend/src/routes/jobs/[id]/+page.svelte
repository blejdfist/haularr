<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { page } from '$app/stores';
  import { onMount, onDestroy } from 'svelte';

  let job = $state<any>(null);
  let events = $state<any[]>([]);
  let loading = $state(true);
  let eventSource: EventSource | null = null;

  const jobId = $page.params.id;

  async function load() {
    loading = true;
    try {
      job = await endpoints.jobs.get(jobId);
      events = await endpoints.jobs.events(jobId);
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    await load();

    // SSE for live updates
    eventSource = new EventSource('/api/v1/events');
    eventSource.addEventListener('snapshot', (e) => {
      const data = JSON.parse(e.data);
      const liveJob = data.jobs?.find((j: any) => j.id === jobId);
      if (liveJob && job) {
        job.status = liveJob.status;
        job.stage = liveJob.stage;
        job.download_bytes_done = liveJob.bytes_done;
        job.download_bytes_total = liveJob.bytes_total;
      }
    });

    // Poll for events every 5s as fallback
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  });

  onDestroy(() => {
    eventSource?.close();
  });

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

  function stageColor(status: string): string {
    const map: Record<string, string> = {
      succeeded: 'text-green-400',
      running: 'text-blue-400',
      queued: 'text-slate-400',
      skipped: 'text-slate-600',
      failed: 'text-red-500',
      retry_wait: 'text-orange-400',
      needs_attention: 'text-red-400',
    };
    return map[status] ?? 'text-slate-400';
  }

  function formatBytes(bytes: number): string {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${units[i]}`;
  }

  const pipelineStages = [
    'resolve_source', 'download', 'verify', 'extract',
    'publish', 'inspect_import', 'import', 'confirm_import', 'notify', 'cleanup'
  ];
</script>

<div class="p-6">
  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if job}
    <div class="mb-6">
      <a href="/jobs/" class="text-blue-400 text-sm hover:text-blue-300">← Back to Jobs</a>
    </div>

    <!-- Header -->
    <div class="mb-6 p-4 bg-slate-900 rounded-lg border border-slate-700">
      <div class="flex justify-between items-start">
        <div>
          <div class="flex items-center gap-3 mb-2">
            <span class="font-mono text-sm">{job.id}</span>
            <span class={statusColor(job.status)}>{job.status}</span>
            <span class="px-2 py-0.5 text-xs bg-slate-700 rounded">{job.stage}</span>
          </div>
          {#if job.error_detail}
            <div class="text-sm text-red-400">{job.error_detail}</div>
          {/if}
        </div>
        <div class="flex gap-2">
          {#if job.status === 'running' || job.status === 'queued'}
            <button onclick={() => endpoints.jobs.pause(job.id).then(load)} class="px-3 py-1 text-xs bg-yellow-700 hover:bg-yellow-600 rounded">Pause</button>
          {/if}
          {#if job.status === 'paused'}
            <button onclick={() => endpoints.jobs.resume(job.id).then(load)} class="px-3 py-1 text-xs bg-green-700 hover:bg-green-600 rounded">Resume</button>
          {/if}
          {#if job.status === 'failed' || job.status === 'needs_attention'}
            <button onclick={() => endpoints.jobs.retry(job.id).then(load)} class="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 rounded">Retry</button>
          {/if}
          {#if job.status !== 'completed' && job.status !== 'cancelled'}
            <button onclick={() => endpoints.jobs.cancel(job.id).then(load)} class="px-3 py-1 text-xs bg-red-700 hover:bg-red-600 rounded">Cancel</button>
          {/if}
          {#if job.stage === 'import' || job.stage === 'inspect_import'}
            <button onclick={() => endpoints.jobs.retryImport(job.id).then(load)} class="px-3 py-1 text-xs bg-purple-700 hover:bg-purple-600 rounded">Retry Import</button>
          {/if}
        </div>
      </div>

      <!-- Progress -->
      {#if job.download_bytes_total > 0}
        <div class="mt-4">
          <div class="flex justify-between text-sm text-slate-400 mb-1">
            <span>Download Progress</span>
            <span>{formatBytes(job.download_bytes_done)} / {formatBytes(job.download_bytes_total)}</span>
          </div>
          <div class="h-3 bg-slate-800 rounded-full overflow-hidden">
            <div class="h-full bg-blue-500 rounded-full transition-all"
              style="width: {Math.min((job.download_bytes_done / job.download_bytes_total) * 100, 100)}%"></div>
          </div>
        </div>
      {/if}
    </div>

    <!-- Pipeline visualization -->
    <div class="mb-6 p-4 bg-slate-900 rounded-lg border border-slate-700">
      <h3 class="text-lg font-semibold mb-4">Pipeline Stages</h3>
      <div class="flex flex-wrap gap-2">
        {#each pipelineStages as stage, i}
          {@const run = job.stage_runs?.find((r: any) => r.stage === stage)}
          {@const isCurrent = job.stage === stage}
          {@const status = run?.status || (i < pipelineStages.indexOf(job.stage) ? 'succeeded' : 'pending')}
          <div class="flex items-center gap-2">
            <div class="px-3 py-2 rounded text-sm border
              {isCurrent ? 'border-blue-400 bg-blue-900/30' : 'border-slate-700 bg-slate-800'}
              {stageColor(status)}">
              {stage}
              {#if run?.attempt > 1}
                <span class="ml-1 text-xs text-orange-400">×{run.attempt}</span>
              {/if}
            </div>
            {#if i < pipelineStages.length - 1}
              <span class="text-slate-600">→</span>
            {/if}
          </div>
        {/each}
      </div>
    </div>

    <!-- Stage runs -->
    {#if job.stage_runs?.length > 0}
      <div class="mb-6 p-4 bg-slate-900 rounded-lg border border-slate-700">
        <h3 class="text-lg font-semibold mb-4">Stage Runs</h3>
        <div class="grid gap-2">
          {#each job.stage_runs as run}
            <div class="flex items-center gap-3 text-sm">
              <span class={stageColor(run.status)}>{run.status}</span>
              <span class="font-mono">{run.stage}</span>
              <span class="text-slate-400">attempt {run.attempt}</span>
              {#if run.error_detail}
                <span class="text-red-400 text-xs">{run.error_detail}</span>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Files -->
    {#if job.files?.length > 0}
      <div class="mb-6 p-4 bg-slate-900 rounded-lg border border-slate-700">
        <h3 class="text-lg font-semibold mb-4">Files</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-slate-400 border-b border-slate-700">
                <th class="px-2 py-1">File</th>
                <th class="px-2 py-1">Size</th>
                <th class="px-2 py-1">Received</th>
                <th class="px-2 py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {#each job.files as file}
                <tr class="border-b border-slate-800">
                  <td class="px-2 py-2 font-mono text-xs">{file.remote_relpath}</td>
                  <td class="px-2 py-2">{formatBytes(file.size_bytes)}</td>
                  <td class="px-2 py-2">{formatBytes(file.bytes_received)}</td>
                  <td class="px-2 py-2">
                    <span class="text-xs {file.transfer_status === 'completed' ? 'text-green-400' : 'text-yellow-400'}">
                      {file.transfer_status}
                    </span>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}

    <!-- Event timeline -->
    {#if events?.length > 0}
      <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <h3 class="text-lg font-semibold mb-4">Event Timeline</h3>
        <div class="grid gap-1">
          {#each events as event}
            <div class="flex items-start gap-3 text-sm py-1.5 border-b border-slate-800">
              <span class="text-xs text-slate-500 font-mono whitespace-nowrap">
                {new Date(event.created_at).toLocaleTimeString()}
              </span>
              <span class="px-1.5 py-0.5 text-xs rounded
                {event.severity === 'error' ? 'bg-red-900 text-red-300' :
                 event.severity === 'warning' ? 'bg-yellow-900 text-yellow-300' :
                 'bg-slate-700 text-slate-300'}">
                {event.severity}
              </span>
              <span class="text-slate-300">{event.message}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>

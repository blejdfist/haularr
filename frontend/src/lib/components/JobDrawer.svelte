<script lang="ts">
  import { Drawer, Button, Badge, Timeline, TimelineItem, Alert } from 'flowbite-svelte';
  import { endpoints } from '$lib/api/client';
  import { groupOf, badgeColor, parseUtc } from '$lib/status';

  let { jobId, open = $bindable(false), onchanged }: {
    jobId: string | null;
    open: boolean;
    onchanged: () => void;
  } = $props();

  let job = $state<any>(null);
  let events = $state<any[]>([]);
  let error = $state('');
  let busy = $state(false);

  async function load(id: string) {
    error = '';
    try {
      [job, events] = await Promise.all([endpoints.jobs.get(id), endpoints.jobs.events(id)]);
    } catch (e: any) {
      error = e.message;
    }
  }

  $effect(() => {
    if (open && jobId) {
      job = null;
      events = [];
      load(jobId);
    }
  });

  async function act(fn: (id: string) => Promise<any>) {
    if (!jobId) return;
    busy = true;
    error = '';
    try {
      await fn(jobId);
      await load(jobId);
      onchanged();
    } catch (e: any) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const group = $derived(job ? groupOf(job.status) : null);
  const fmt = (s: string | null) => (s ? parseUtc(s).toLocaleString() : '');
  const size = (n: number | null) => (n == null ? '' : `${(n / 1048576).toFixed(1)} MB`);
</script>

<Drawer bind:open placement="right" class="w-full max-w-xl overflow-y-auto">
  {#if job}
    <div class="space-y-4">
      <div>
        <h3 class="text-lg font-semibold break-words">{job.config_snapshot?.title ?? '—'}</h3>
        <div class="mt-1 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <Badge color={badgeColor(job.status)}>{job.status}</Badge>
          <span>{job.stage}</span>
          <span>attempts: {job.attempts}</span>
        </div>
      </div>

      {#if error}<Alert color="red">{error}</Alert>{/if}
      {#if job.error_detail}
        <Alert color="red">
          <span class="font-medium">{job.error_code ?? 'Error'}</span>
          <pre class="mt-1 text-xs whitespace-pre-wrap">{job.error_detail}</pre>
        </Alert>
      {/if}

      <div class="flex flex-wrap gap-2">
        {#if group === 'failed'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.retry)}>Retry</Button>
          <Button size="xs" color="alternative" disabled={busy} onclick={() => act(endpoints.jobs.retryImport)}>Retry import</Button>
        {/if}
        {#if job.status === 'running' || job.status === 'queued'}
          <Button size="xs" color="yellow" disabled={busy} onclick={() => act(endpoints.jobs.pause)}>Pause</Button>
        {/if}
        {#if job.status === 'paused'}
          <Button size="xs" disabled={busy} onclick={() => act(endpoints.jobs.resume)}>Resume</Button>
        {/if}
        {#if group === 'active'}
          <Button size="xs" color="red" disabled={busy} onclick={() => act(endpoints.jobs.cancel)}>Cancel</Button>
        {/if}
      </div>

      <section>
        <h4 class="mb-2 font-semibold">Stages</h4>
        {#if job.stage_runs?.length}
          <Timeline>
            {#each job.stage_runs as r}
              <TimelineItem title="{r.stage} · attempt {r.attempt} · {r.status}" date={fmt(r.started_at)}>
                {#if r.error_detail}
                  <p class="text-sm text-red-600 dark:text-red-400">{r.error_code}: {r.error_detail}</p>
                {/if}
              </TimelineItem>
            {/each}
          </Timeline>
        {:else}
          <p class="text-sm text-gray-500">No stages yet.</p>
        {/if}
      </section>

      <section>
        <h4 class="mb-2 font-semibold">Files</h4>
        <ul class="space-y-1 text-sm">
          {#each job.files ?? [] as f}
            <li class="flex justify-between gap-2">
              <span class="break-all">{f.remote_relpath}</span>
              <span class="whitespace-nowrap text-gray-500">{f.transfer_status} · {size(f.bytes_received)} / {size(f.size_bytes)}</span>
            </li>
          {:else}
            <li class="text-gray-500">No files.</li>
          {/each}
        </ul>
      </section>

      <section>
        <h4 class="mb-2 font-semibold">Events</h4>
        <ul class="space-y-2 text-sm">
          {#each events as e}
            <li class={e.severity === 'error' ? 'text-red-600 dark:text-red-400' : ''}>
              <span class="text-gray-500">{fmt(e.created_at)}</span> <span class="font-mono">{e.kind}</span> {e.message}
              {#if e.severity === 'error' && e.details}
                <pre class="mt-1 text-xs whitespace-pre-wrap">{JSON.stringify(e.details, null, 2)}</pre>
              {/if}
            </li>
          {:else}
            <li class="text-gray-500">No events.</li>
          {/each}
        </ul>
      </section>
    </div>
  {:else if error}
    <Alert color="red">{error}</Alert>
  {:else}
    <p class="text-gray-500">Loading…</p>
  {/if}
</Drawer>

<script lang="ts">
  import { onMount } from 'svelte';
  import { Alert, Button, Input, Label, Spinner } from 'flowbite-svelte';
  import { endpoints, api } from '$lib/api/client';

  const fields = [
    ['max_concurrent_download_jobs', 'Max concurrent download jobs'],
    ['max_concurrent_verify_jobs', 'Max concurrent verify jobs'],
    ['max_concurrent_extract_jobs', 'Max concurrent extract jobs'],
    ['max_concurrent_publish_jobs', 'Max concurrent publish jobs'],
    ['max_concurrent_import_jobs', 'Max concurrent import jobs'],
    ['completed_history_days', 'Completed history (days)'],
    ['discovery_interval_seconds', 'Discovery interval (seconds)'],
    ['retry_limit', 'Retry limit'],
    ['stage_lease_seconds', 'Stage lease (seconds)'],
  ] as const;

  let values = $state<Record<string, number>>({});
  let loading = $state(true);
  let saving = $state(false);
  let message = $state<{ ok: boolean; text: string } | null>(null);

  function load(s: Record<string, any>) {
    values = Object.fromEntries(fields.map(([k]) => [k, s[k]]));
  }

  onMount(async () => {
    try {
      load(await endpoints.settings.get());
    } catch (e) {
      message = { ok: false, text: (e as Error).message };
    } finally {
      loading = false;
    }
  });

  async function save(e: Event) {
    e.preventDefault();
    saving = true;
    message = null;
    try {
      load(await endpoints.settings.patch(values));
      message = { ok: true, text: 'Settings saved.' };
    } catch (err) {
      message = { ok: false, text: (err as Error).message };
    } finally {
      saving = false;
    }
  }

  async function exportConfig() {
    try {
      const data = await api.get<unknown>('/config/export');
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
      );
      const a = Object.assign(document.createElement('a'), { href: url, download: 'haularr-config.json' });
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message = { ok: false, text: (err as Error).message };
    }
  }
</script>

<h1 class="mb-4 text-2xl font-bold">Settings</h1>

{#if message}
  <Alert color={message.ok ? 'green' : 'red'} class="mb-4">{message.text}</Alert>
{/if}

{#if loading}
  <Spinner />
{:else}
  <form onsubmit={save} class="grid max-w-xl gap-4">
    {#each fields as [key, label]}
      <div>
        <Label for={key} class="mb-1">{label}</Label>
        <Input id={key} type="number" min="0" bind:value={values[key]} />
      </div>
    {/each}
    <div class="flex gap-2">
      <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      <Button type="button" color="alternative" onclick={exportConfig}>Export config</Button>
    </div>
  </form>
{/if}

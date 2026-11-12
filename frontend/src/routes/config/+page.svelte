<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let activeTab = $state('transfers');
  let transfers = $state<any[]>([]);
  let libraries = $state<any[]>([]);
  let settings = $state<any>(null);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const [t, l, s] = await Promise.all([
        endpoints.transfers.list(),
        endpoints.libraries.list(),
        endpoints.settings.get(),
      ]);
      transfers = t;
      libraries = l;
      settings = s;
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  const tabs = [
    { id: 'transfers', label: 'Transfers' },
    { id: 'libraries', label: 'Libraries' },
    { id: 'settings', label: 'Settings' },
  ];
</script>

<div class="p-6">
  <h2 class="text-2xl font-bold mb-6">Configuration</h2>

  <div class="flex gap-1 mb-6 border-b border-slate-700">
    {#each tabs as tab}
      <button onclick={() => (activeTab = tab.id)}
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors
          {activeTab === tab.id ? 'border-blue-400 text-blue-400' : 'border-transparent text-slate-400 hover:text-slate-200'}">
        {tab.label}
      </button>
    {/each}
  </div>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if activeTab === 'transfers'}
    <div class="grid gap-3">
      {#each transfers as t}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="flex justify-between">
            <div>
              <span class="font-semibold">{t.name}</span>
              <span class="ml-2 px-2 py-0.5 text-xs bg-slate-700 rounded">{t.adapter_type}</span>
            </div>
            <button onclick={() => endpoints.transfers.test(t.id)} class="px-2 py-1 text-xs bg-slate-700 rounded">Test</button>
          </div>
          {#if t.endpoints?.length}
            <div class="mt-2 text-sm text-slate-400">
              Endpoints: {t.endpoints.map((e: any) => e.name).join(', ')}
            </div>
          {/if}
        </div>
      {/each}
      {#if transfers.length === 0}
        <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">No transfers configured.</div>
      {/if}
    </div>
  {:else if activeTab === 'libraries'}
    <div class="grid gap-3">
      {#each libraries as l}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="flex justify-between">
            <div>
              <span class="font-semibold">{l.name}</span>
              <span class="ml-2 px-2 py-0.5 text-xs bg-slate-700 rounded">{l.adapter_type}</span>
              <span class="ml-2 text-sm text-slate-400">{l.base_url}</span>
            </div>
            <button onclick={() => endpoints.libraries.test(l.id)} class="px-2 py-1 text-xs bg-slate-700 rounded">Test</button>
          </div>
        </div>
      {/each}
      {#if libraries.length === 0}
        <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">No libraries configured.</div>
      {/if}
    </div>
  {:else if activeTab === 'settings' && settings}
    <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
      <div class="grid grid-cols-2 gap-4">
        <label class="block">
          <span class="text-sm text-slate-400">Max Concurrent Downloads</span>
          <input type="number" bind:value={settings.max_concurrent_download_jobs}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Max Concurrent Verify</span>
          <input type="number" bind:value={settings.max_concurrent_verify_jobs}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Max Concurrent Extract</span>
          <input type="number" bind:value={settings.max_concurrent_extract_jobs}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Completed History Days</span>
          <input type="number" bind:value={settings.completed_history_days}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Discovery Interval (s)</span>
          <input type="number" bind:value={settings.discovery_interval_seconds}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Retry Limit</span>
          <input type="number" bind:value={settings.retry_limit}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
      </div>
      <button onclick={async () => { await endpoints.settings.patch(settings); alert('Saved'); }}
        class="mt-4 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-semibold">
        Save Settings
      </button>
    </div>
  {/if}
</div>

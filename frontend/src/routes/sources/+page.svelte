<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let sources = $state<any[]>([]);
  let loading = $state(true);
  let showCreate = $state(false);
  let newSource = $state({ name: '', adapter_type: 'rtorrent', connection_secret_ref: '', poll_interval: 30, enabled: true });

  async function load() {
    loading = true;
    try {
      sources = await endpoints.sources.list();
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  async function create() {
    try {
      await endpoints.sources.create(newSource);
      showCreate = false;
      newSource = { name: '', adapter_type: 'rtorrent', connection_secret_ref: '', poll_interval: 30, enabled: true };
      await load();
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }

  async function testSource(id: string) {
    try {
      const result = await endpoints.sources.test(id);
      alert(result.ok ? `Connected! Version: ${result.version}` : `Failed: ${result.error}`);
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }

  async function scanSource(id: string) {
    try {
      await endpoints.sources.scan(id);
      await load();
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }

  async function completeOnboarding(id: string) {
    try {
      await endpoints.sources.completeOnboarding(id);
      await load();
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }
</script>

<div class="p-6">
  <div class="flex justify-between items-center mb-6">
    <h2 class="text-2xl font-bold">Sources</h2>
    <button onclick={() => (showCreate = !showCreate)} class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-semibold">
      {showCreate ? 'Cancel' : '+ Add Source'}
    </button>
  </div>

  {#if showCreate}
    <div class="p-4 bg-slate-900 rounded-lg border border-slate-700 mb-6">
      <h3 class="text-lg font-semibold mb-4">New Source</h3>
      <div class="grid grid-cols-2 gap-4">
        <label class="block">
          <span class="text-sm text-slate-400">Name</span>
          <input bind:value={newSource.name} class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Adapter Type</span>
          <select bind:value={newSource.adapter_type} class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm">
            <option value="rtorrent">rTorrent</option>
            <option value="deluge">Deluge</option>
          </select>
        </label>
        <label class="block col-span-2">
          <span class="text-sm text-slate-400">Connection Config (JSON)</span>
          <textarea bind:value={newSource.connection_secret_ref} rows="3"
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm font-mono"
            placeholder={"{\"xmlrpc_url\": \"https://host/RPC2\"}"}
          ></textarea>
        </label>
        <label class="block">
          <span class="text-sm text-slate-400">Poll Interval (seconds)</span>
          <input type="number" bind:value={newSource.poll_interval} class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>
      </div>
      <button onclick={create} class="mt-4 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-semibold">
        Create
      </button>
    </div>
  {/if}

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if sources.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">
      No sources configured. Click "Add Source" to create one.
    </div>
  {:else}
    <div class="grid gap-4">
      {#each sources as source}
        <div class="p-4 bg-slate-900 rounded-lg border border-slate-700">
          <div class="flex justify-between items-start">
            <div>
              <div class="flex items-center gap-3">
                <span class="w-2 h-2 rounded-full {source.enabled ? 'bg-green-500' : 'bg-slate-600'}"></span>
                <h3 class="text-lg font-semibold">{source.name}</h3>
                <span class="px-2 py-0.5 text-xs bg-slate-700 rounded">{source.adapter_type}</span>
              </div>
              <div class="mt-2 text-sm text-slate-400">
                Onboarding: <span class="font-mono">{source.onboarding_state}</span>
                {#if source.last_scan_at}
                  · Last scan: {source.last_scan_at}
                {/if}
              </div>
            </div>
            <div class="flex gap-2">
              <button onclick={() => testSource(source.id)} class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">Test</button>
              <button onclick={() => scanSource(source.id)} class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">Scan</button>
              {#if source.onboarding_state === 'awaiting_review'}
                <button onclick={() => completeOnboarding(source.id)} class="px-3 py-1 text-xs bg-green-700 hover:bg-green-600 rounded">
                  Complete Onboarding
                </button>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

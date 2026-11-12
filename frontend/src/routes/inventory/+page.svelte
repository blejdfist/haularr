<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import { onMount } from 'svelte';

  let items = $state<any[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let filterSource = $state('');
  let filterEligibility = $state('');
  let search = $state('');
  let offset = $state(0);
  let limit = $state(50);

  async function load() {
    loading = true;
    try {
      const params: Record<string, string> = { offset: String(offset), limit: String(limit) };
      if (filterSource) params.source_id = filterSource;
      if (filterEligibility) params.eligibility = filterEligibility;
      if (search) params.search = search;
      const data = await endpoints.sourceItems.list(params);
      items = data.items;
      total = data.total;
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function eligibilityColor(status: string | null): string {
    const map: Record<string, string> = {
      missing: 'text-red-400',
      already_available: 'text-green-400',
      not_registered: 'text-orange-400',
      needs_review: 'text-yellow-400',
      unrouted: 'text-slate-500',
      ignored: 'text-slate-600',
    };
    return map[status ?? ''] ?? 'text-slate-400';
  }

  async function queueItem(id: string, force: boolean = false) {
    try {
      await endpoints.sourceItems.queue(id, force);
      await load();
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }

  async function ignoreItem(id: string) {
    try {
      await endpoints.sourceItems.ignore(id);
      await load();
    } catch (e) {
      alert(`Failed: ${e}`);
    }
  }
</script>

<div class="p-6">
  <h2 class="text-2xl font-bold mb-6">Source Inventory</h2>

  <!-- Filters -->
  <div class="flex gap-4 mb-6">
    <input bind:value={search} oninput={() => (offset = 0)} placeholder="Search titles..."
      class="px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm w-64" />
    <select bind:value={filterSource} onchange={() => (offset = 0)}
      class="px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm">
      <option value="">All Sources</option>
    </select>
    <select bind:value={filterEligibility} onchange={() => (offset = 0)}
      class="px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm">
      <option value="">All Statuses</option>
      <option value="missing">Missing</option>
      <option value="already_available">Already Available</option>
      <option value="not_registered">Not Registered</option>
      <option value="needs_review">Needs Review</option>
      <option value="unrouted">Unrouted</option>
      <option value="ignored">Ignored</option>
    </select>
    <button onclick={load} class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-semibold">
      Search
    </button>
  </div>

  {#if loading}
    <div class="text-slate-400">Loading...</div>
  {:else if items.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">
      No source items found.
    </div>
  {:else}
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-slate-400 border-b border-slate-700">
            <th class="px-3 py-2">Title</th>
            <th class="px-3 py-2">Labels</th>
            <th class="px-3 py-2">Status</th>
            <th class="px-3 py-2">Eligibility</th>
            <th class="px-3 py-2">Size</th>
            <th class="px-3 py-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each items as item}
            <tr class="border-b border-slate-800 hover:bg-slate-900">
              <td class="px-3 py-3 font-mono text-xs">{item.title}</td>
              <td class="px-3 py-3">
                {#each item.labels as label}
                  <span class="px-2 py-0.5 text-xs bg-slate-700 rounded mr-1">{label}</span>
                {/each}
              </td>
              <td class="px-3 py-3">
                <span class="text-xs {item.source_status === 'completed' ? 'text-green-400' : 'text-yellow-400'}">
                  {item.source_status}
                </span>
              </td>
              <td class="px-3 py-3 {eligibilityColor(item.last_eligibility)}">
                {item.last_eligibility ?? '—'}
              </td>
              <td class="px-3 py-3 text-xs">
                {(item.size_bytes / 1e9).toFixed(2)} GB
              </td>
              <td class="px-3 py-3">
                <button onclick={() => queueItem(item.id)} class="px-2 py-1 text-xs bg-blue-700 hover:bg-blue-600 rounded mr-1">
                  Queue
                </button>
                <button onclick={() => queueItem(item.id, true)} class="px-2 py-1 text-xs bg-orange-700 hover:bg-orange-600 rounded mr-1">
                  Force
                </button>
                <button onclick={() => ignoreItem(item.id)} class="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">
                  Ignore
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="mt-4 text-sm text-slate-400">
      Showing {items.length} of {total} items
    </div>
  {/if}
</div>

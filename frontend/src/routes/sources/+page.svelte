<script lang="ts">
  import { endpoints } from '$lib/api/client';
  import SourceConfigForm from '$lib/components/SourceConfigForm.svelte';
  import { onMount } from 'svelte';

  // ---- Types ----
  type Source = {
    id: string;
    name: string;
    adapter_type: string;
    enabled: boolean;
    has_credential: boolean;
    connection_config: Record<string, any>;
    poll_interval: number;
    onboarding_state: string;
    last_scan_at: string | null;
    label_rules?: LabelRule[];
  };

  type LabelRule = {
    id: string;
    source_id: string;
    label: string;
    enabled: boolean;
    automatic_processing: boolean;
    temporary_directory: string;
    completed_directory: string;
    library_instance_id: string | null;
    priority: number;
  };

  // ---- State ----
  let sources = $state<Source[]>([]);
  let loading = $state(true);

  // Create form
  let showCreate = $state(false);
  let createForm = $state({
    name: '',
    adapter_type: 'rtorrent',
    connection_config: { port: 443, tls_verify: true, url_path: 'rutorrent/plugins/rpc/rpc.php' } as Record<string, any>,
    credential: '',
    poll_interval: 30,
    enabled: true,
  });
  let creating = $state(false);
  let createError = $state('');

  // Edit form (one at a time)
  let editingId = $state<string | null>(null);
  let editForm = $state({
    name: '',
    adapter_type: '',
    connection_config: {} as Record<string, any>,
    credential: '',  // blank = keep existing
    poll_interval: 30,
    enabled: true,
  });
  let saving = $state(false);
  let saveError = $state('');

  // Label rules modal
  let labelsSourceId = $state<string | null>(null);
  let labelRules = $state<LabelRule[]>([]);
  let newLabel = $state({
    label: '',
    temporary_directory: '',
    completed_directory: '',
    library_instance_id: null as string | null,
    enabled: true,
    automatic_processing: false,
  });
  let addingLabel = $state(false);

  // ---- Helpers ----
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

  function adapterLabel(type: string): string {
    return type === 'rtorrent' ? 'rTorrent / ruTorrent' : type === 'deluge' ? 'Deluge' : type;
  }

  function onboardingBadge(state: string): string {
    const map: Record<string, string> = {
      pending: 'bg-slate-700 text-slate-300',
      scanning: 'bg-blue-900 text-blue-300',
      awaiting_review: 'bg-yellow-900 text-yellow-300',
      completed: 'bg-green-900 text-green-300',
    };
    return map[state] ?? 'bg-slate-700 text-slate-300';
  }

  // Reset adapter-specific defaults when type changes
  function onAdapterTypeChange(type: string, isEdit = false) {
    const defaults: Record<string, Record<string, any>> = {
      rtorrent: { port: 443, tls_verify: true, url_path: 'rutorrent/plugins/rpc/rpc.php' },
      deluge:   { port: 8112, tls_verify: false },
    };
    if (isEdit) {
      editForm.adapter_type = type;
      editForm.connection_config = { ...defaults[type] };
      editForm.credential = '';
    } else {
      createForm.adapter_type = type;
      createForm.connection_config = { ...defaults[type] };
      createForm.credential = '';
    }
  }

  // ---- Create ----
  async function create() {
    createError = '';
    creating = true;
    try {
      await endpoints.sources.create({
        name: createForm.name,
        adapter_type: createForm.adapter_type,
        connection_config: createForm.connection_config,
        credential: createForm.credential,
        poll_interval: createForm.poll_interval,
        enabled: createForm.enabled,
      });
      showCreate = false;
      createForm = {
        name: '',
        adapter_type: 'rtorrent',
        connection_config: { port: 443, tls_verify: true, url_path: 'rutorrent/plugins/rpc/rpc.php' },
        credential: '',
        poll_interval: 30,
        enabled: true,
      };
      await load();
    } catch (e: any) {
      createError = e.message || 'Failed to create source';
    } finally {
      creating = false;
    }
  }

  // ---- Edit ----
  function startEdit(source: Source) {
    editingId = source.id;
    saveError = '';
    editForm = {
      name: source.name,
      adapter_type: source.adapter_type,
      connection_config: { ...source.connection_config },
      credential: '', // blank means keep existing
      poll_interval: source.poll_interval,
      enabled: source.enabled,
    };
  }

  function cancelEdit() {
    editingId = null;
    saveError = '';
  }

  async function saveEdit(sourceId: string) {
    saveError = '';
    saving = true;
    try {
      const payload: Record<string, any> = {
        name: editForm.name,
        connection_config: editForm.connection_config,
        poll_interval: editForm.poll_interval,
        enabled: editForm.enabled,
      };
      // Only send credential if it was changed
      if (editForm.credential) {
        payload.credential = editForm.credential;
      }
      await endpoints.sources.update(sourceId, payload);
      editingId = null;
      await load();
    } catch (e: any) {
      saveError = e.message || 'Failed to save';
    } finally {
      saving = false;
    }
  }

  async function deleteSource(id: string) {
    if (!confirm('Delete this source? This also removes all label rules.')) return;
    try {
      await endpoints.sources.delete(id);
      await load();
    } catch (e: any) {
      alert(`Failed: ${e.message}`);
    }
  }

  // ---- Test saved source ----
  let testingId = $state<string | null>(null);
  let testResults = $state<Record<string, any>>({});

  async function testSaved(id: string) {
    testingId = id;
    try {
      const r = await endpoints.sources.test(id);
      testResults = { ...testResults, [id]: r };
    } catch (e: any) {
      testResults = { ...testResults, [id]: { ok: false, error: e.message } };
    } finally {
      testingId = null;
    }
  }

  // ---- Scan / Onboarding ----
  async function triggerScan(id: string) {
    try {
      await endpoints.sources.scan(id);
      await load();
    } catch (e: any) { alert(`Failed: ${e.message}`); }
  }

  async function completeOnboarding(id: string) {
    try {
      await endpoints.sources.completeOnboarding(id);
      await load();
    } catch (e: any) { alert(`Failed: ${e.message}`); }
  }

  // ---- Label rules ----
  async function openLabels(source: Source) {
    labelsSourceId = source.id;
    try {
      labelRules = await endpoints.sources.labels.list(source.id);
    } catch (e) { console.error(e); }
  }

  async function addLabel() {
    if (!labelsSourceId) return;
    addingLabel = true;
    try {
      await endpoints.sources.labels.create(labelsSourceId, newLabel);
      labelRules = await endpoints.sources.labels.list(labelsSourceId);
      newLabel = { label: '', temporary_directory: '', completed_directory: '', library_instance_id: null, enabled: true, automatic_processing: false };
    } catch (e: any) { alert(`Failed: ${e.message}`); }
    finally { addingLabel = false; }
  }

  async function deleteLabel(ruleId: string) {
    if (!labelsSourceId) return;
    await endpoints.sources.labels.delete(labelsSourceId, ruleId);
    labelRules = await endpoints.sources.labels.list(labelsSourceId);
  }
</script>

<div class="p-6">
  <div class="flex justify-between items-center mb-6">
    <h2 class="text-2xl font-bold">Sources</h2>
    <button
      onclick={() => { showCreate = !showCreate; createError = ''; }}
      class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-semibold"
    >
      {showCreate ? 'Cancel' : '+ Add Source'}
    </button>
  </div>

  <!-- ============================================================
       Create form
  ============================================================ -->
  {#if showCreate}
    <div class="mb-6 p-5 bg-slate-900 rounded-xl border border-slate-700">
      <h3 class="text-lg font-semibold mb-4">New Source</h3>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <label class="block">
          <span class="text-sm text-slate-400">Name</span>
          <input bind:value={createForm.name}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm"
            placeholder="Primary seedbox" />
        </label>

        <label class="block">
          <span class="text-sm text-slate-400">Adapter type</span>
          <select
            value={createForm.adapter_type}
            onchange={(e) => onAdapterTypeChange((e.target as HTMLSelectElement).value)}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm"
          >
            <option value="rtorrent">rTorrent / ruTorrent</option>
            <option value="deluge">Deluge</option>
          </select>
        </label>

        <label class="block">
          <span class="text-sm text-slate-400">Poll interval (seconds)</span>
          <input type="number" bind:value={createForm.poll_interval}
            class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
        </label>

        <label class="flex items-center gap-2 mt-5 cursor-pointer">
          <input type="checkbox" bind:checked={createForm.enabled}
            class="w-4 h-4 rounded border-slate-600 bg-slate-800" />
          <span class="text-sm text-slate-300">Enabled</span>
        </label>
      </div>

      <div class="p-4 bg-slate-800 rounded-lg border border-slate-600 mb-4">
        <h4 class="text-sm font-medium text-slate-300 mb-3">Connection</h4>
        <SourceConfigForm
          adapterType={createForm.adapter_type}
          config={createForm.connection_config}
          credential={createForm.credential}
          onConfigChange={(c) => (createForm.connection_config = c)}
          onCredentialChange={(v) => (createForm.credential = v)}
        />
      </div>

      {#if createError}
        <p class="text-sm text-red-400 mb-3">{createError}</p>
      {/if}

      <button
        onclick={create}
        disabled={creating || !createForm.name || !createForm.adapter_type}
        class="px-5 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-40 rounded-lg text-sm font-semibold"
      >
        {creating ? 'Creating…' : 'Create source'}
      </button>
    </div>
  {/if}

  <!-- ============================================================
       Source list
  ============================================================ -->
  {#if loading}
    <div class="text-slate-400">Loading…</div>
  {:else if sources.length === 0}
    <div class="text-slate-400 p-4 bg-slate-900 rounded-lg border border-slate-700">
      No sources configured. Click <strong>+ Add Source</strong> to get started.
    </div>
  {:else}
    <div class="grid gap-4">
      {#each sources as source}
        <div class="bg-slate-900 rounded-xl border {editingId === source.id ? 'border-blue-500' : 'border-slate-700'}">

          <!-- ---- Header row ---- -->
          <div class="flex justify-between items-start p-4">
            <div class="flex items-start gap-3">
              <div class="mt-0.5 w-2.5 h-2.5 rounded-full {source.enabled ? 'bg-green-500' : 'bg-slate-600'}"></div>
              <div>
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-lg font-semibold">{source.name}</span>
                  <span class="px-2 py-0.5 text-xs bg-slate-700 rounded">{adapterLabel(source.adapter_type)}</span>
                  <span class="px-2 py-0.5 text-xs rounded {onboardingBadge(source.onboarding_state)}">
                    {source.onboarding_state.replace('_', ' ')}
                  </span>
                  {#if source.has_credential}
                    <span class="px-2 py-0.5 text-xs bg-slate-700 text-slate-400 rounded" title="Credential stored encrypted">🔑</span>
                  {/if}
                </div>
                {#if source.connection_config?.host}
                  <p class="text-xs text-slate-400 mt-1 font-mono">{source.connection_config.host}:{source.connection_config.port}</p>
                {/if}
                {#if source.last_scan_at}
                  <p class="text-xs text-slate-500 mt-0.5">Last scan: {new Date(source.last_scan_at).toLocaleString()}</p>
                {/if}
              </div>
            </div>

            <!-- Action buttons -->
            <div class="flex flex-wrap gap-1.5 justify-end">
              {#if editingId === source.id}
                <button onclick={() => saveEdit(source.id)} disabled={saving}
                  class="px-3 py-1 text-xs bg-green-700 hover:bg-green-600 disabled:opacity-40 rounded font-semibold">
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button onclick={cancelEdit}
                  class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">Cancel</button>
              {:else}
                <button onclick={() => startEdit(source)}
                  class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">Edit</button>
                <button onclick={() => triggerScan(source.id)}
                  class="px-3 py-1 text-xs bg-blue-800 hover:bg-blue-700 rounded">Scan</button>
                <button onclick={() => openLabels(source)}
                  class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">Labels</button>
                {#if source.onboarding_state === 'awaiting_review'}
                  <button onclick={() => completeOnboarding(source.id)}
                    class="px-3 py-1 text-xs bg-green-800 hover:bg-green-700 rounded font-semibold">
                    Complete onboarding
                  </button>
                {/if}
                <button onclick={() => testSaved(source.id)} disabled={testingId === source.id}
                  class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded">
                  {testingId === source.id ? '…' : 'Test'}
                </button>
                <button onclick={() => deleteSource(source.id)}
                  class="px-3 py-1 text-xs bg-red-900 hover:bg-red-800 rounded">Delete</button>
              {/if}
            </div>
          </div>

          <!-- Test result for saved source -->
          {#if testResults[source.id]}
            {@const r = testResults[source.id]}
            <div class="mx-4 mb-3 px-3 py-2 rounded text-sm
              {r.ok ? 'bg-green-950 border border-green-800 text-green-300' : 'bg-red-950 border border-red-800 text-red-300'}">
              {#if r.ok}
                ✓ Connected — {r.version ? `v${r.version}` : 'OK'}
                {#if r.warning}<span class="text-yellow-400 ml-2">⚠ {r.warning}</span>{/if}
                {#if r.label_plugin_enabled === false}<span class="text-yellow-400 ml-2">⚠ Label plugin not enabled</span>{/if}
              {:else}
                ✗ {r.error || 'Connection failed'}
              {/if}
            </div>
          {/if}

          <!-- ---- Edit form (inline) ---- -->
          {#if editingId === source.id}
            <div class="px-4 pb-4 border-t border-slate-700 pt-4">
              <div class="grid grid-cols-2 gap-4 mb-4">
                <label class="block">
                  <span class="text-sm text-slate-400">Name</span>
                  <input bind:value={editForm.name}
                    class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
                </label>
                <label class="block">
                  <span class="text-sm text-slate-400">Poll interval (seconds)</span>
                  <input type="number" bind:value={editForm.poll_interval}
                    class="mt-1 w-full px-3 py-2 bg-slate-800 rounded border border-slate-600 text-sm" />
                </label>
                <label class="flex items-center gap-2 mt-2 cursor-pointer">
                  <input type="checkbox" bind:checked={editForm.enabled}
                    class="w-4 h-4 rounded border-slate-600 bg-slate-800" />
                  <span class="text-sm text-slate-300">Enabled</span>
                </label>
              </div>

              <div class="p-4 bg-slate-800 rounded-lg border border-slate-600">
                <h4 class="text-sm font-medium text-slate-300 mb-3">
                  Connection
                  <span class="text-xs text-slate-500 ml-2">
                    {source.has_credential ? '(leave password blank to keep existing)' : ''}
                  </span>
                </h4>
                <SourceConfigForm
                  adapterType={editForm.adapter_type}
                  config={editForm.connection_config}
                  credential={editForm.credential}
                  onConfigChange={(c) => (editForm.connection_config = c)}
                  onCredentialChange={(v) => (editForm.credential = v)}
                />
              </div>

              {#if saveError}
                <p class="text-sm text-red-400 mt-3">{saveError}</p>
              {/if}
            </div>
          {/if}

          <!-- ---- Label rules summary (inline) ---- -->
          {#if labelsSourceId === source.id}
            <div class="px-4 pb-4 border-t border-slate-700 pt-4">
              <div class="flex items-center justify-between mb-3">
                <h4 class="text-sm font-semibold text-slate-300">Label rules</h4>
                <button onclick={() => (labelsSourceId = null)}
                  class="text-xs text-slate-500 hover:text-slate-300">Close ×</button>
              </div>

              {#if labelRules.length === 0}
                <p class="text-xs text-slate-500 mb-3">No label rules yet.</p>
              {:else}
                <div class="grid gap-1.5 mb-4">
                  {#each labelRules as rule}
                    <div class="flex items-center justify-between px-3 py-2 bg-slate-800 rounded text-sm">
                      <div class="flex items-center gap-3">
                        <span class="font-mono text-blue-300">{rule.label}</span>
                        <span class="text-xs text-slate-400">{rule.temporary_directory} → {rule.completed_directory}</span>
                        {#if !rule.enabled}
                          <span class="text-xs text-slate-600">(disabled)</span>
                        {/if}
                      </div>
                      <button onclick={() => deleteLabel(rule.id)}
                        class="text-xs text-red-500 hover:text-red-400">Remove</button>
                    </div>
                  {/each}
                </div>
              {/if}

              <!-- Add label rule form -->
              <div class="grid grid-cols-2 gap-3 p-3 bg-slate-800 rounded-lg border border-slate-700">
                <label class="block">
                  <span class="text-xs text-slate-400">Label</span>
                  <input bind:value={newLabel.label} placeholder="tv"
                    class="mt-1 w-full px-2 py-1.5 bg-slate-900 rounded border border-slate-600 text-sm font-mono" />
                </label>
                <div></div>
                <label class="block">
                  <span class="text-xs text-slate-400">Temp directory (Path A)</span>
                  <input bind:value={newLabel.temporary_directory} placeholder="/data/temp/source-label"
                    class="mt-1 w-full px-2 py-1.5 bg-slate-900 rounded border border-slate-600 text-sm font-mono" />
                </label>
                <label class="block">
                  <span class="text-xs text-slate-400">Completed directory (Path B)</span>
                  <input bind:value={newLabel.completed_directory} placeholder="/data/completed/source-label"
                    class="mt-1 w-full px-2 py-1.5 bg-slate-900 rounded border border-slate-600 text-sm font-mono" />
                </label>
                <div class="col-span-2 flex justify-end">
                  <button onclick={addLabel} disabled={addingLabel || !newLabel.label || !newLabel.temporary_directory || !newLabel.completed_directory}
                    class="px-3 py-1.5 text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded font-semibold">
                    {addingLabel ? 'Adding…' : '+ Add label rule'}
                  </button>
                </div>
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

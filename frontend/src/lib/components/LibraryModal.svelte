<script lang="ts">
  import { Modal, Button, Input, Label, Select, Alert, Spinner } from 'flowbite-svelte';
  import { endpoints, type Library } from '$lib/api/client';

  let {
    open = $bindable(false),
    library,
    onsaved,
    ondeleted,
  }: { open: boolean; library: Library | null; onsaved: () => void; ondeleted: () => void } = $props();

  const TYPES = [
    { value: 'sonarr', name: 'Sonarr' },
    { value: 'radarr', name: 'Radarr' },
  ];

  let name = $state('');
  let adapterType = $state('sonarr');
  let baseUrl = $state('');
  let apiKey = $state('');
  let importMode = $state<'Copy' | 'Move'>('Copy');
  let maps = $state<{ local_prefix: string; library_prefix: string }[]>([]);
  let error = $state('');
  let saving = $state(false);
  let testing = $state(false);
  let testResult = $state<{ ok: boolean; text: string } | null>(null);
  let tab = $state<'general' | 'paths' | 'advanced'>('general');
  let confirmOpen = $state(false);

  // Reset the form each time the modal opens.
  $effect(() => {
    if (!open) return;
    name = library?.name ?? '';
    adapterType = library?.adapter_type ?? 'sonarr';
    baseUrl = library?.base_url ?? '';
    apiKey = '';
    importMode = library?.options?.import_mode ?? 'Copy';
    maps = (library?.options?.path_mappings ?? []).map((m: any) => ({ ...m }));
    error = '';
    tab = 'general';
  });

  // A test result only describes the values it was run with.
  $effect(() => {
    adapterType;
    baseUrl;
    apiKey;
    testResult = null;
  });

  async function test() {
    testing = true;
    try {
      // Blank key while editing = test with the stored key.
      const r = await endpoints.libraries.testConfig({
        adapter_type: adapterType,
        base_url: baseUrl,
        api_key: apiKey,
        ...(library && !apiKey ? { library_id: library.id } : {}),
      });
      testResult = r.ok
        ? { ok: true, text: `Connected${r.version ? ' (v' + r.version + ')' : ''}` }
        : { ok: false, text: r.error ?? 'Connection failed' };
    } catch (err: any) {
      testResult = { ok: false, text: err.message };
    } finally {
      testing = false;
    }
  }

  async function remove() {
    if (!library) return;
    try {
      await endpoints.libraries.delete(library.id);
      confirmOpen = false;
      open = false;
      ondeleted();
    } catch (err: any) {
      confirmOpen = false;
      error = err.message;
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saving = true;
    error = '';
    try {
      const options = {
        ...(library?.options ?? {}),
        import_mode: importMode,
        path_mappings: maps.filter((m) => m.local_prefix && m.library_prefix),
      };
      if (library) {
        // Blank key = keep stored one: omit the field (backend ignores nulls).
        await endpoints.libraries.update(library.id, {
          name,
          base_url: baseUrl,
          options,
          ...(apiKey ? { api_key_secret_ref: apiKey } : {}),
        });
      } else {
        await endpoints.libraries.create({
          name,
          adapter_type: adapterType as 'sonarr' | 'radarr',
          base_url: baseUrl,
          api_key_secret_ref: apiKey,
          options,
        });
      }
      open = false;
      onsaved();
    } catch (err: any) {
      error = err.message;
    } finally {
      saving = false;
    }
  }
</script>

{#snippet tabButton(id: 'general' | 'paths' | 'advanced', label: string)}
  <button
    type="button"
    role="tab"
    aria-selected={tab === id}
    class="-mb-px border-b-2 px-4 py-2 text-sm font-medium {tab === id
      ? 'border-primary-500 text-primary-500'
      : 'border-transparent text-gray-500 hover:text-gray-300 dark:text-gray-400'}"
    onclick={() => (tab = id)}>{label}</button
  >
{/snippet}

<Modal bind:open title={library ? `Edit library: ${library.name}` : 'Add library'} size="md">
  <!-- required fields live on General: show it when the browser blocks submit -->
  <form onsubmit={save} oninvalidcapture={() => (tab = 'general')} class="flex flex-col gap-4">
    {#if error}<Alert color="red">{error}</Alert>{/if}
    <div role="tablist" class="flex border-b border-gray-200 dark:border-gray-700">
      {@render tabButton('general', 'General')}
      {@render tabButton('paths', `Path mappings${maps.length ? ` (${maps.length})` : ''}`)}
      {@render tabButton('advanced', 'Advanced')}
    </div>
    <section class="flex flex-col gap-4" class:hidden={tab !== 'general'}>
      <div>
        <Label for="lib-name" class="mb-2">Name</Label>
        <Input id="lib-name" bind:value={name} required />
      </div>
      <div>
        <Label for="lib-type" class="mb-2">Type</Label>
        <Select id="lib-type" items={TYPES} bind:value={adapterType} disabled={!!library} />
      </div>
      <div>
        <div class="mb-2 flex items-baseline justify-between">
          <Label for="lib-url">Base URL</Label>
          {#if /^https?:\/\//i.test(baseUrl)}
            <a href={baseUrl} target="_blank" rel="noopener noreferrer" class="text-xs text-primary-500 hover:underline">Open ↗</a>
          {/if}
        </div>
        <Input id="lib-url" type="url" bind:value={baseUrl} placeholder="http://sonarr:8989" required />
      </div>
      <div>
        <Label for="lib-key" class="mb-2">API key</Label>
        <Input
          id="lib-key"
          type="password"
          autocomplete="off"
          bind:value={apiKey}
          required={!library}
          placeholder={library ? 'Leave blank to keep the current key' : ''}
        />
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <Button size="sm" color="alternative" disabled={testing || !baseUrl || (!library && !apiKey)} onclick={test}>
          {#if testing}<Spinner size="4" class="me-2" />{/if}Test connection
        </Button>
        {#if testResult}
          <span class="text-sm {testResult.ok ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-300'}"
            >{testResult.text}</span
          >
        {/if}
      </div>
    </section>
    <section class="space-y-2" class:hidden={tab !== 'paths'}>
      <p class="text-sm text-gray-500 dark:text-gray-400">
        Only needed when {adapterType === 'radarr' ? 'Radarr' : 'Sonarr'} sees Haularr's folders under other paths, e.g. in
        Docker: <code>D:\Temp\haularr\downloads</code> → <code>/downloads</code>.
      </p>
      {#each maps as m, i}
        <div class="flex gap-2">
          <Input placeholder="D:\downloads" aria-label="Haularr path" bind:value={m.local_prefix} />
          <Input placeholder="/downloads" aria-label="Library path" bind:value={m.library_prefix} />
          <Button size="xs" color="alternative" onclick={() => maps.splice(i, 1)}>Remove</Button>
        </div>
      {/each}
      <Button size="xs" color="alternative" onclick={() => maps.push({ local_prefix: '', library_prefix: '' })}
        >Add mapping</Button
      >
    </section>
    <section class:hidden={tab !== 'advanced'}>
      <Label for="lib-import-mode" class="mb-2">Import mode</Label>
      <Select
        id="lib-import-mode"
        items={[{ value: 'Copy', name: 'Copy' }, { value: 'Move', name: 'Move' }]}
        bind:value={importMode}
        aria-describedby="lib-import-mode-help"
      />
      <p id="lib-import-mode-help" class="mt-2 text-sm text-gray-500 dark:text-gray-400">
        {importMode === 'Copy'
          ? 'The library copies files. Haularr removes the source files after confirming the import.'
          : 'The library moves files and needs permission to delete the source files.'}
      </p>
    </section>
    <div class="flex flex-wrap items-center gap-2 border-t border-gray-200 pt-4 dark:border-gray-700">
      {#if library}<Button color="red" outline onclick={() => (confirmOpen = true)}>Delete</Button>{/if}
      <Button color="alternative" class="ms-auto" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" color="primary" disabled={saving}>
        {#if saving}<Spinner size="4" class="me-2" />{/if}Save
      </Button>
    </div>
  </form>
</Modal>

<Modal bind:open={confirmOpen} title="Delete library" size="xs">
  <p>Delete <strong>{library?.name}</strong>? This cannot be undone.</p>
  <div class="mt-4 flex justify-end gap-2">
    <Button color="alternative" onclick={() => (confirmOpen = false)}>Cancel</Button>
    <Button color="red" onclick={remove}>Delete</Button>
  </div>
</Modal>

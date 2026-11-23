<script lang="ts">
  import { Modal, Button, Input, Label, Select, Alert, Spinner } from 'flowbite-svelte';
  import { endpoints, type Library } from '$lib/api/client';

  let { open = $bindable(false), library, onsaved }: { open: boolean; library: Library | null; onsaved: () => void } = $props();

  const TYPES = [
    { value: 'sonarr', name: 'Sonarr' },
    { value: 'radarr', name: 'Radarr' },
  ];

  let name = $state('');
  let adapterType = $state('sonarr');
  let baseUrl = $state('');
  let apiKey = $state('');
  let error = $state('');
  let saving = $state(false);
  let testing = $state(false);
  let testResult = $state<{ ok: boolean; text: string } | null>(null);

  // Reset the form each time the modal opens.
  $effect(() => {
    if (!open) return;
    name = library?.name ?? '';
    adapterType = library?.adapter_type ?? 'sonarr';
    baseUrl = library?.base_url ?? '';
    apiKey = '';
    error = '';
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

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saving = true;
    error = '';
    try {
      if (library) {
        // Blank key = keep stored one: omit the field (backend ignores nulls).
        await endpoints.libraries.update(library.id, {
          name,
          base_url: baseUrl,
          ...(apiKey ? { api_key_secret_ref: apiKey } : {}),
        });
      } else {
        await endpoints.libraries.create({
          name,
          adapter_type: adapterType as 'sonarr' | 'radarr',
          base_url: baseUrl,
          api_key_secret_ref: apiKey,
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

<Modal bind:open title={library ? 'Edit library' : 'Add library'} size="md">
  <form onsubmit={save} class="flex flex-col gap-4">
    {#if error}<Alert color="red">{error}</Alert>{/if}
    <div>
      <Label for="lib-name" class="mb-2">Name</Label>
      <Input id="lib-name" bind:value={name} required />
    </div>
    <div>
      <Label for="lib-type" class="mb-2">Type</Label>
      <Select id="lib-type" items={TYPES} bind:value={adapterType} disabled={!!library} />
    </div>
    <div>
      <Label for="lib-url" class="mb-2">Base URL</Label>
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
    {#if testResult}<Alert color={testResult.ok ? 'green' : 'red'}>{testResult.text}</Alert>{/if}
    <div class="flex justify-end gap-2">
      <Button
        color="alternative"
        class="me-auto"
        disabled={testing || !baseUrl || (!library && !apiKey)}
        onclick={test}
      >
        {#if testing}<Spinner size="4" class="me-2" />{/if}Test connection
      </Button>
      <Button color="alternative" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" color="primary" disabled={saving}>
        {#if saving}<Spinner size="4" class="me-2" />{/if}Save
      </Button>
    </div>
  </form>
</Modal>

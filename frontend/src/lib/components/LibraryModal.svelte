<script lang="ts">
  import { Modal, Button, Input, Label, Select, Alert } from 'flowbite-svelte';
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

  // Reset the form each time the modal opens.
  $effect(() => {
    if (!open) return;
    name = library?.name ?? '';
    adapterType = library?.adapter_type ?? 'sonarr';
    baseUrl = library?.base_url ?? '';
    apiKey = '';
    error = '';
  });

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
    <div class="flex justify-end gap-2">
      <Button color="alternative" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
    </div>
  </form>
</Modal>

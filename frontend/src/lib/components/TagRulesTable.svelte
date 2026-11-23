<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Input, Select, Toggle, Alert } from 'flowbite-svelte';
  import { endpoints, type LabelRule, type Library } from '$lib/api/client';

  let { sourceId, libraries, seenLabels }: { sourceId: string; libraries: Library[]; seenLabels: string[] } = $props();

  type Row = { id: string | null; label: string; library: string; tmp: string; done: string; enabled: boolean };
  let rows = $state<Row[]>([]);
  let error = $state('');
  let busy = $state<Record<number, boolean>>({});

  const libItems = $derived([
    { value: '', name: 'Select library...' },
    ...libraries.map((l) => ({ value: l.id, name: `${l.name} (${l.adapter_type})` })),
  ]);

  const toRow = (r: LabelRule): Row => ({
    id: r.id,
    label: r.label,
    library: r.library_instance_id ?? '',
    tmp: r.temporary_directory,
    done: r.completed_directory,
    enabled: r.enabled,
  });

  onMount(async () => {
    try {
      rows = (await endpoints.sources.labels.list(sourceId)).map(toRow);
    } catch (e: any) {
      error = e.message;
    }
  });

  async function save(i: number) {
    const r = rows[i];
    busy[i] = true;
    error = '';
    try {
      const body = {
        label: r.label,
        library_instance_id: r.library || null,
        temporary_directory: r.tmp,
        completed_directory: r.done,
        enabled: r.enabled,
        automatic_processing: true,
      };
      if (r.id) {
        const { label: _l, ...patch } = body; // label is immutable server-side
        rows[i] = toRow(await endpoints.sources.labels.update(sourceId, r.id, patch));
      } else {
        rows[i] = toRow(await endpoints.sources.labels.create(sourceId, body));
      }
    } catch (e: any) {
      error = e.message;
    }
    busy[i] = false;
  }

  async function remove(i: number) {
    const r = rows[i];
    error = '';
    try {
      if (r.id) await endpoints.sources.labels.delete(sourceId, r.id);
      rows.splice(i, 1);
    } catch (e: any) {
      error = e.message;
    }
  }
</script>

<div class="space-y-3">
  <datalist id="seen-labels">
    {#each seenLabels as l}<option value={l}></option>{/each}
  </datalist>
  {#if error}<Alert color="red">{error}</Alert>{/if}
  {#each rows as r, i (r.id ?? i)}
    <div class="grid grid-cols-1 items-center gap-2 rounded-lg border border-gray-200 p-3 md:grid-cols-6 dark:border-gray-700">
      <Input placeholder="Tag" list="seen-labels" bind:value={r.label} disabled={!!r.id} />
      <Select items={libItems} bind:value={r.library} />
      <Input placeholder="Temporary dir" bind:value={r.tmp} />
      <Input placeholder="Completed dir" bind:value={r.done} />
      <Toggle bind:checked={r.enabled}>Enabled</Toggle>
      <div class="flex gap-2">
        <Button size="xs" disabled={busy[i] || !r.label || !r.library || !r.tmp || !r.done} onclick={() => save(i)}>
          {r.id ? 'Save' : 'Add'}
        </Button>
        <Button size="xs" color="red" onclick={() => remove(i)}>Delete</Button>
      </div>
    </div>
  {/each}
  {#if !rows.length}<p class="text-sm text-gray-500 dark:text-gray-400">No tag mappings yet.</p>{/if}
  <Button
    size="xs"
    color="alternative"
    onclick={() => rows.push({ id: null, label: '', library: '', tmp: '', done: '', enabled: true })}>Add tag</Button
  >
</div>

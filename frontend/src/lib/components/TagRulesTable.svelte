<script lang="ts">
  import { onMount } from 'svelte';
  import { Button, Input, Label, Select, Toggle, Alert, Badge, Spinner } from 'flowbite-svelte';
  import { PenOutline, TrashBinOutline } from 'flowbite-svelte-icons';
  import { endpoints, type LabelRule, type Library } from '$lib/api/client';

  let {
    sourceId,
    libraries,
    seenLabels,
    onchange,
    count = $bindable(0),
  }: { sourceId: string; libraries: Library[]; seenLabels: string[]; onchange?: () => void; count?: number } =
    $props();

  type Row = { id: string | null; label: string; library: string; tmp: string; done: string; enabled: boolean };
  let rules = $state<LabelRule[]>([]);
  // Row being edited: index into rules, or -1 for a new tag; null = none
  let editing = $state<number | null>(null);
  let draft = $state<Row>({ id: null, label: '', library: '', tmp: '', done: '', enabled: true });
  let error = $state('');
  let busy = $state(false);

  const libItems = $derived([
    { value: '', name: 'Select library...' },
    ...libraries.map((l) => ({ value: l.id, name: `${l.name} (${l.adapter_type})` })),
  ]);
  const libName = (id: string | null) => libraries.find((l) => l.id === id)?.name ?? '—';

  onMount(async () => {
    try {
      rules = await endpoints.sources.labels.list(sourceId);
    } catch (e: any) {
      error = e.message;
    }
  });

  function edit(i: number) {
    const r = rules[i];
    draft = {
      id: r.id,
      label: r.label,
      library: r.library_instance_id ?? '',
      tmp: r.temporary_directory,
      done: r.completed_directory,
      enabled: r.enabled,
    };
    editing = i;
    error = '';
  }

  function add() {
    draft = { id: null, label: '', library: '', tmp: '', done: '', enabled: true };
    editing = -1;
    error = '';
  }

  async function save() {
    busy = true;
    error = '';
    try {
      const body = {
        label: draft.label.trim(),
        library_instance_id: draft.library || null,
        temporary_directory: draft.tmp,
        completed_directory: draft.done,
        enabled: draft.enabled,
        automatic_processing: true,
      };
      if (draft.id && editing !== null && editing >= 0) {
        rules[editing] = await endpoints.sources.labels.update(sourceId, draft.id, body);
      } else {
        rules.push(await endpoints.sources.labels.create(sourceId, body));
      }
      editing = null;
      onchange?.();
    } catch (e: any) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function remove(i: number) {
    error = '';
    try {
      await endpoints.sources.labels.delete(sourceId, rules[i].id);
      rules.splice(i, 1);
      if (editing === i) editing = null;
      onchange?.();
    } catch (e: any) {
      error = e.message;
    }
  }

  $effect(() => {
    count = rules.length;
  });

  const valid = $derived(!!draft.label.trim() && !!draft.library && !!draft.tmp && !!draft.done);
</script>

{#snippet form()}
  <div class="grid gap-3 rounded-lg border border-primary-500/50 p-3 md:grid-cols-2">
    <div>
      <Label for="t-label" class="mb-1">Tag *</Label>
      <Input id="t-label" list="seen-labels" bind:value={draft.label} placeholder="tv-sonarr" />
    </div>
    <div>
      <Label for="t-lib" class="mb-1">Library *</Label>
      <Select id="t-lib" items={libItems} bind:value={draft.library} />
    </div>
    <div>
      <Label for="t-tmp" class="mb-1">Temporary folder *</Label>
      <Input id="t-tmp" bind:value={draft.tmp} placeholder="/data/incoming" />
    </div>
    <div>
      <Label for="t-done" class="mb-1">Completed folder *</Label>
      <Input id="t-done" bind:value={draft.done} placeholder="/data/completed" />
    </div>
    <div class="flex items-center justify-between gap-2 md:col-span-2">
      <Toggle bind:checked={draft.enabled}>Enabled</Toggle>
      <div class="flex gap-2">
        <Button size="xs" color="alternative" onclick={() => (editing = null)}>Cancel</Button>
        <Button size="xs" disabled={busy || !valid} onclick={save}>
          {#if busy}<Spinner size="4" class="me-1" />{/if}{draft.id ? 'Save tag' : 'Add tag'}
        </Button>
      </div>
    </div>
  </div>
{/snippet}

<div class="space-y-2">
  <datalist id="seen-labels">
    {#each seenLabels as l}<option value={l}></option>{/each}
  </datalist>
  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#each rules as r, i (r.id)}
    {#if editing === i}
      {@render form()}
    {:else}
      <div class="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-700">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="font-medium">{r.label}</span>
            <span class="text-gray-400">→</span>
            <span>{libName(r.library_instance_id)}</span>
            {#if !r.enabled}<Badge color="gray">Disabled</Badge>{/if}
          </div>
          <div class="truncate text-xs text-gray-500 dark:text-gray-400">
            {r.temporary_directory} → {r.completed_directory}
          </div>
        </div>
        <Button size="xs" color="alternative" aria-label="Edit tag {r.label}" onclick={() => edit(i)}>
          <PenOutline class="h-4 w-4" />
        </Button>
        <Button size="xs" color="alternative" aria-label="Delete tag {r.label}" onclick={() => remove(i)}>
          <TrashBinOutline class="h-4 w-4 text-red-500" />
        </Button>
      </div>
    {/if}
  {/each}

  {#if editing === -1}
    {@render form()}
  {:else if !rules.length}
    <p class="text-sm text-gray-500 dark:text-gray-400">No tags mapped yet.</p>
  {/if}

  {#if editing === null}
    <Button size="xs" color="alternative" onclick={add}>Add tag</Button>
  {/if}
</div>

<script lang="ts">
  import { Button, Input, Label, Select, Toggle, Badge } from 'flowbite-svelte';
  import { PenOutline, TrashBinOutline } from 'flowbite-svelte-icons';
  import type { LabelRule, Library } from '$lib/api/client';
  import FileBrowserInput from './FileBrowserInput.svelte';

  // Pure editor: changes stay in `rules` until the parent saves them.
  let {
    rules = $bindable([]),
    libraries,
    seenLabels,
  }: { rules: LabelRule[]; libraries: Library[]; seenLabels: string[] } = $props();

  type Row = { id: string | null; label: string; library: string; tmp: string; done: string; enabled: boolean };
  // Rule id being edited, 'new' for a new tag, null = none (id, not index: rows can be deleted while editing)
  let editing = $state<string | null>(null);
  let draft = $state<Row>({ id: null, label: '', library: '', tmp: '', done: '', enabled: true });
  let nextDraftId = 0;

  const libItems = $derived([
    { value: '', name: 'Select library...' },
    ...libraries.map((l) => ({ value: l.id, name: `${l.name} (${l.adapter_type})` })),
  ]);
  const libName = (id: string | null) => libraries.find((l) => l.id === id)?.name ?? '—';

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
    editing = r.id;
  }

  function add() {
    draft = { id: null, label: '', library: '', tmp: '', done: '', enabled: true };
    editing = 'new';
  }

  function save() {
    const fields = {
      label: draft.label.trim(),
      library_instance_id: draft.library || null,
      temporary_directory: draft.tmp,
      completed_directory: draft.done,
      enabled: draft.enabled,
      automatic_processing: true,
    };
    rules = draft.id
      ? rules.map((r) => (r.id === draft.id ? { ...r, ...fields } : r))
      : [...rules, { ...fields, id: String(++nextDraftId) } as LabelRule];
    editing = null;
  }

  function remove(i: number) {
    const id = rules[i].id;
    rules = rules.filter((r) => r.id !== id);
    if (editing === id) editing = null;
  }

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
      <FileBrowserInput id="t-tmp" bind:value={draft.tmp} label="Temporary folder" placeholder="/data/incoming" />
    </div>
    <div>
      <Label for="t-done" class="mb-1">Completed folder *</Label>
      <FileBrowserInput id="t-done" bind:value={draft.done} label="Completed folder" placeholder="/data/completed" />
    </div>
    <div class="flex items-center justify-between gap-2 md:col-span-2">
      <Toggle bind:checked={draft.enabled}>Enabled</Toggle>
      <div class="flex gap-2">
        <Button size="xs" color="alternative" onclick={() => (editing = null)}>Cancel</Button>
        <Button size="xs" disabled={!valid} onclick={save}>
          {draft.id ? 'Update tag' : 'Add tag'}
        </Button>
      </div>
    </div>
  </div>
{/snippet}

<div class="space-y-2">
  <datalist id="seen-labels">
    {#each seenLabels as l}<option value={l}></option>{/each}
  </datalist>

  {#each rules as r, i (r.id)}
    {#if editing === r.id}
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

  {#if editing === 'new'}
    {@render form()}
  {:else if !rules.length}
    <p class="text-sm text-gray-500 dark:text-gray-400">No tags mapped yet.</p>
  {/if}

  {#if editing === null}
    <Button size="xs" color="alternative" onclick={add}>Add tag</Button>
  {/if}
</div>

<script lang="ts">
  import { Input, Modal } from 'flowbite-svelte';
  import { FolderOutline } from 'flowbite-svelte-icons';
  import FileBrowser from './FileBrowser.svelte';

  let {
    id,
    value = $bindable(''),
    placeholder = '',
    label = 'Server folder',
    disabled = false,
  }: {
    id: string;
    value?: string;
    placeholder?: string;
    label?: string;
    disabled?: boolean;
  } = $props();

  let open = $state(false);
  let browseButton: HTMLButtonElement;

  function close() {
    open = false;
  }
</script>

<div class="relative">
  <Input {id} bind:value {placeholder} {disabled} class="pe-12" />
  <button bind:this={browseButton} type="button" {disabled}
    class="absolute inset-y-0 end-0 flex w-11 items-center justify-center rounded-e-lg text-gray-600 hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-primary-500 disabled:opacity-50 dark:text-gray-300 dark:hover:text-primary-400"
    aria-label={`Browse ${label.toLowerCase()}`} title={`Browse ${label.toLowerCase()}`}
    onclick={() => (open = true)}>
    <FolderOutline class="h-5 w-5" />
  </button>
</div>

<Modal bind:open title={`Select ${label.toLowerCase()}`} aria-label={`Select ${label.toLowerCase()}`} size="lg"
  onclose={() => { if (!open) browseButton?.focus(); }}>
  {#if open}
    <FileBrowser initialPath={value} oncancel={close} onselect={(path) => { value = path; close(); }} />
  {/if}
</Modal>

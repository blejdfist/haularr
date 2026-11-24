<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Alert } from 'flowbite-svelte';

  // Shared shell for the Sources and Libraries pages, so both put their cards in the same place.
  let {
    title,
    error = '',
    empty,
    actions,
    children,
  }: {
    title: string;
    error?: string;
    /** Shown instead of the grid when set (no items yet). */
    empty?: string;
    actions: Snippet;
    children: Snippet;
  } = $props();
</script>

<div class="space-y-4">
  <!-- Fixed height: bordered (alternative) buttons are 2px taller than filled ones. -->
  <div class="flex h-10 items-center justify-between gap-2">
    <h1 class="text-2xl font-bold">{title}</h1>
    <div class="flex gap-2 [&_button]:h-10">{@render actions()}</div>
  </div>

  {#if error}<Alert color="red">{error}</Alert>{/if}

  {#if empty}
    <p class="text-gray-500 dark:text-gray-400">{empty}</p>
  {:else}
    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{@render children()}</div>
  {/if}
</div>

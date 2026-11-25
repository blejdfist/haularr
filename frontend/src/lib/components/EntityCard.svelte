<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Badge } from 'flowbite-svelte';
  import { ChevronRightOutline } from 'flowbite-svelte-icons';
  import type { Dot } from '$lib/status';


  let {
    name,
    dot,
    dotText,
    badge,
    badgeColor = 'gray',
    onclick,
    children,
  }: {
    name: string;
    dot: Dot;
    dotText: string;
    badge: string;
    badgeColor?: 'blue' | 'yellow' | 'green' | 'red' | 'gray' | 'purple' | 'indigo';
    onclick: () => void;
    children?: Snippet;
  } = $props();

  const DOT: Record<Dot, string> = {
    ok: 'bg-green-500',
    error: 'bg-red-500',
    never: 'bg-gray-400',
    checking: 'bg-primary-500',
  };

  // A check or scan that lands OK ripples the dot once: the connection just answered.
  let prev: Dot | undefined;
  let landed = $state(0);
  $effect(() => {
    if (dot === 'ok' && prev === 'checking') landed++;
    prev = dot;
  });
</script>

<button
  type="button"
  {onclick}
  class="group flex w-full flex-col gap-1.5 rounded-lg border bg-white p-4 text-left shadow-xs transition-colors hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 dark:bg-gray-800 dark:hover:bg-gray-700/60 {dot === 'error'
    ? 'border-red-200 dark:border-red-900/60'
    : 'border-gray-200 dark:border-gray-700'}"
>
  <span class="flex items-center gap-2">
    <span class="relative flex h-2.5 w-2.5 shrink-0" title={dotText}>
      {#if dot === 'checking'}
        <span class="absolute inset-0 rounded-full bg-primary-400 opacity-75 motion-safe:animate-ping"></span>
      {/if}
      {#key landed}
        {#if landed}<span class="landed absolute inset-0 rounded-full bg-green-500"></span>{/if}
      {/key}
      <span class="relative h-full w-full rounded-full transition-colors duration-500 {DOT[dot]}"></span>
    </span>
    <span class="sr-only">{dotText}</span>
    <span class="min-w-0 flex-1 truncate text-lg font-semibold text-gray-900 dark:text-white">{name}</span>
    <Badge color={badgeColor}>{badge}</Badge>
    <!-- Zero-width at rest so the badge keeps the edge; slides in to say "opens editor". -->
    <span
      class="-ms-2 -me-1 flex w-0 shrink-0 overflow-hidden opacity-0 transition-all duration-200 ease-out group-hover:ms-0 group-hover:w-4 group-hover:opacity-100 group-focus-visible:ms-0 group-focus-visible:w-4 group-focus-visible:opacity-100"
      aria-hidden="true"
    >
      <ChevronRightOutline class="h-4 w-4 shrink-0 text-gray-400" />
    </span>
  </span>
  <span class="truncate text-sm {dot === 'error' ? 'text-red-700 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}">
    {@render children?.()}
  </span>
</button>

<style>
  .landed {
    animation: landed 900ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }
  @keyframes landed {
    from {
      transform: scale(1);
      opacity: 0.7;
    }
    to {
      transform: scale(3.4);
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .landed {
      display: none;
    }
  }
</style>

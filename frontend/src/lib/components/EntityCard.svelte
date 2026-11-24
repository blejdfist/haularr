<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Badge } from 'flowbite-svelte';
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
    checking: 'bg-gray-400 animate-pulse',
  };
</script>

<button
  type="button"
  {onclick}
  class="flex w-full flex-col gap-1.5 rounded-lg border border-gray-200 bg-white p-4 text-left shadow-xs transition-colors hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700/60"
>
  <span class="flex items-center gap-2">
    <span class="h-2.5 w-2.5 shrink-0 rounded-full {DOT[dot]}" title={dotText}></span>
    <span class="sr-only">{dotText}</span>
    <span class="min-w-0 flex-1 truncate text-lg font-semibold text-gray-900 dark:text-white">{name}</span>
    <Badge color={badgeColor}>{badge}</Badge>
  </span>
  <span class="truncate text-sm text-gray-500 dark:text-gray-400">{@render children?.()}</span>
</button>

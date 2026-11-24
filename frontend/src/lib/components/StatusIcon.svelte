<script lang="ts">
  import type { IconKind } from '$lib/status';

  let { kind, tip, class: cls = 'h-5 w-5' }: { kind: IconKind; tip?: string; class?: string } = $props();

  const LABEL: Record<IconKind, string> = {
    running: 'Running',
    queued: 'Waiting',
    pending: 'Not started',
    done: 'Done',
    failed: 'Failed',
    warning: 'Needs attention',
    skipped: 'Skipped',
  };

  // fixed-position tooltip: escapes overflow-clipping parents like scrollable tables
  let pos = $state<{ x: number; y: number } | null>(null);
  function show(e: Event) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    pos = { x: r.left + r.width / 2, y: r.top - 6 };
  }
</script>

{#snippet icon()}
  <svg viewBox="0 0 24 24" class="{cls} shrink-0 {kind === 'running' ? 'animate-spin' : ''}" aria-hidden="true">
    {#if kind === 'running'}
      <circle cx="12" cy="12" r="9" fill="none" stroke-width="3" class="stroke-blue-500/25" />
      <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke-width="3" stroke-linecap="round" class="stroke-blue-500" />
    {:else if kind === 'done'}
      <circle cx="12" cy="12" r="10" class="fill-green-600" />
      <path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
    {:else if kind === 'failed'}
      <circle cx="12" cy="12" r="10" class="fill-red-600" />
      <path d="m8.5 8.5 7 7m0-7-7 7" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" />
    {:else if kind === 'warning'}
      <path d="M10.3 3.4a2 2 0 0 1 3.4 0l8.4 14.6a2 2 0 0 1-1.7 3H3.6a2 2 0 0 1-1.7-3z" class="fill-amber-500" />
      <path d="M12 9v4.5m0 3.2v.1" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" />
    {:else if kind === 'queued'}
      <circle cx="12" cy="12" r="9" fill="none" stroke-width="2" class="stroke-gray-400" />
      <path d="M12 7.5V12l3 2" fill="none" stroke-width="2" stroke-linecap="round" class="stroke-gray-400" />
    {:else if kind === 'skipped'}
      <circle cx="12" cy="12" r="10" class="fill-gray-400 dark:fill-gray-500" />
      <path d="M8 12h8" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" />
    {:else}
      <circle cx="12" cy="12" r="8" fill="none" stroke-width="2" class="stroke-gray-300 dark:stroke-gray-600" />
    {/if}
  </svg>
{/snippet}

{#if tip}
  <button
    type="button"
    aria-label="{LABEL[kind]}: {tip}"
    class="inline-flex cursor-help rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
    onclick={(e) => e.stopPropagation()}
    onmouseenter={show}
    onfocus={show}
    onmouseleave={() => (pos = null)}
    onblur={() => (pos = null)}>{@render icon()}</button
  >
  {#if pos}
    <span
      role="tooltip"
      class="pointer-events-none fixed z-50 w-max max-w-xs -translate-x-1/2 -translate-y-full whitespace-normal break-words rounded-md bg-gray-900 px-2.5 py-1.5 text-xs font-normal text-gray-50 shadow-lg"
      style="left: {pos.x}px; top: {pos.y}px">{tip}</span
    >
  {/if}
{:else}
  <span class="inline-flex" role="img" aria-label={LABEL[kind]}>{@render icon()}</span>
{/if}

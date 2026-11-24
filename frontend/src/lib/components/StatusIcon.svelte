<script lang="ts">
  import type { IconKind } from '$lib/status';
  import { Spinner } from 'flowbite-svelte';
  import {
    CheckCircleSolid,
    CloseCircleSolid,
    ExclamationCircleSolid,
    ClockOutline,
    CircleMinusSolid,
  } from 'flowbite-svelte-icons';

  /** draw: the job just finished in front of the user; the done mark pops in. */
  let {
    kind,
    tip,
    draw = false,
    class: cls = 'h-5 w-5',
  }: { kind: IconKind; tip?: string; draw?: boolean; class?: string } = $props();

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
  {#if kind === 'running'}
    <!-- flowbite icons draw a 20/24 glyph; the spinner fills its box, so shrink it to match -->
    <Spinner color="blue" class="{cls} m-0 shrink-0 scale-[0.84] text-blue-500/25 dark:text-blue-500/25" />
  {:else if kind === 'done'}
    <CheckCircleSolid class="{cls} shrink-0 text-green-600 {draw ? 'status-pop' : ''}" />
  {:else if kind === 'failed'}
    <CloseCircleSolid class="{cls} shrink-0 text-red-600" />
  {:else if kind === 'warning'}
    <ExclamationCircleSolid class="{cls} shrink-0 text-amber-500" />
  {:else if kind === 'queued'}
    <ClockOutline class="{cls} shrink-0 text-gray-400" />
  {:else if kind === 'skipped'}
    <CircleMinusSolid class="{cls} shrink-0 text-gray-400 dark:text-gray-500" />
  {:else}
    <span class="{cls} inline-block shrink-0 scale-75 rounded-full border-2 border-gray-300 dark:border-gray-600"></span>
  {/if}
{/snippet}

{#if tip}
  <button
    type="button"
    aria-label="{LABEL[kind]}: {tip}"
    class="flex cursor-help rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
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
  <span class="flex" role="img" aria-label={LABEL[kind]}>{@render icon()}</span>
{/if}

<style>
  :global(.status-pop) {
    animation: status-pop 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  }
  @keyframes -global-status-pop {
    from {
      transform: scale(0.5);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    :global(.status-pop) {
      animation: none;
    }
  }
</style>

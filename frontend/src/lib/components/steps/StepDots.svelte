<script lang="ts">
  import { currentIndex, type Step } from './types';

  let { steps }: { steps: Step[] } = $props();

  const cur = $derived(currentIndex(steps));
  const allDone = $derived(steps.every((s) => s.state === 'done' || s.state === 'skipped'));

  const pill: Record<string, string> = {
    active: 'bg-blue-600 animate-pulse',
    waiting: 'bg-amber-600',
    failed: 'bg-red-600',
    pending: 'bg-gray-500',
    done: 'bg-green-600',
    skipped: 'bg-green-600',
  };
</script>

<span class="inline-flex items-center whitespace-nowrap">
  {#each steps as s, i (s.key)}
    {#if i > 0}
      <span class="h-0.5 w-3 {i <= cur ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-400'}"></span>
    {/if}
    {#if i === cur}
      <span
        class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold text-white {allDone ? 'bg-green-600' : pill[s.state]}"
      >
        {s.label}
        {#if s.state === 'active' && s.progress != null}
          <span class="h-1 w-10 overflow-hidden rounded bg-white/35">
            <span class="block h-full bg-white" style="width: {s.progress}%"></span>
          </span>
        {/if}
      </span>
      {#if s.reason}
        <span class="group relative ml-1 inline-flex">
          <button
            type="button"
            aria-label={s.reason}
            class="cursor-help text-sm leading-none text-amber-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded"
            onclick={(e) => e.stopPropagation()}>⚠</button
          >
          <span
            role="tooltip"
            class="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded-md bg-gray-900 px-2.5 py-1.5 text-xs font-normal text-gray-50 shadow-lg group-hover:block group-focus-within:block"
            >{s.reason}</span
          >
        </span>
      {/if}
    {:else}
      <span
        class="inline-block shrink-0 rounded-full {s.state === 'skipped'
          ? 'h-1.5 w-1.5 bg-gray-400'
          : i < cur
            ? 'h-2.5 w-2.5 bg-blue-500'
            : 'h-2 w-2 border-2 border-gray-400 dark:border-gray-400'}"
      ></span>
    {/if}
  {/each}
</span>

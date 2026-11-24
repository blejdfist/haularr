<script lang="ts">
  import type { Snippet } from 'svelte';
  import { CheckOutline, CloseOutline, ExclamationCircleOutline } from 'flowbite-svelte-icons';
  import { currentIndex, type Step } from './types';

  let {
    steps,
    selected = $bindable<string | undefined>(),
    detail,
  }: { steps: Step[]; selected?: string; detail?: Snippet<[Step]> } = $props();

  const cur = $derived(currentIndex(steps));
  const sel = $derived(steps.find((s) => s.key === selected) ?? steps[cur]);

  const node: Record<string, string> = {
    done: 'bg-green-600 text-white',
    skipped: 'bg-green-600 text-white',
    active: 'bg-blue-600 text-white ring-4 ring-blue-500/30',
    waiting: 'bg-amber-600 text-white ring-4 ring-amber-500/30',
    failed: 'bg-red-600 text-white ring-4 ring-red-500/30',
    pending: 'bg-white dark:bg-gray-800 border-2 border-gray-300 text-gray-500 dark:border-gray-500 dark:text-gray-400',
  };
  const STATE: Record<Step['state'], string> = {
    done: 'done',
    skipped: 'skipped',
    active: 'in progress',
    waiting: 'needs attention',
    failed: 'failed',
    pending: 'not started',
  };
</script>

<div>
  <ol class="flex">
    {#each steps as s, i (s.key)}
      <li class="relative flex flex-1 justify-center">
        {#if i < steps.length - 1}
          <span
            class="absolute left-1/2 top-3.5 h-0.5 w-full {i < cur ? 'bg-green-600' : 'bg-gray-300 dark:bg-gray-600'}"
          ></span>
        {/if}
        <button
          type="button"
          class="relative z-10 flex flex-col items-center gap-1.5 rounded-md px-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          aria-current={sel?.key === s.key ? 'step' : undefined}
          onclick={() => (selected = s.key)}
        >
          <span class="flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold {node[s.state]}">
            {#if s.state === 'done' || s.state === 'skipped'}
              <CheckOutline class="h-4 w-4" strokeWidth="3" aria-hidden="true" />
            {:else if s.state === 'failed'}
              <CloseOutline class="h-4 w-4" strokeWidth="3" aria-hidden="true" />
            {:else if s.state === 'waiting'}
              <ExclamationCircleOutline class="h-4 w-4" strokeWidth="2.5" aria-hidden="true" />
            {:else if s.state === 'active'}
              {i + 1}
            {/if}
          </span>
          <span
            class="text-xs whitespace-nowrap {sel?.key === s.key
              ? 'font-semibold text-gray-900 dark:text-white'
              : `max-sm:sr-only ${s.state === 'pending' ? 'text-gray-500 dark:text-gray-400' : 'text-gray-700 dark:text-gray-200'}`}"
            >{s.label}<span class="sr-only">, {STATE[s.state]}</span></span
          >
        </button>
      </li>
    {/each}
  </ol>
  {#if detail && sel}
    <div class="mt-3 rounded-lg bg-gray-50 p-3 dark:bg-gray-700/40">
      {@render detail(sel)}
    </div>
  {/if}
</div>

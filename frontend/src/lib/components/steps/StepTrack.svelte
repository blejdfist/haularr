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

  // Marks drawn after the first frame animate in: a step finishing while you watch. Opening
  // the drawer stays still.
  let armed = $state(false);
  $effect(() => {
    const t = requestAnimationFrame(() => (armed = true));
    return () => cancelAnimationFrame(t);
  });

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

  /*
    The connector out of each step. Behind the current step it is done (green). Out of the
    running step it carries the work toward the next one: filled to the stage's percentage
    when there is one, a travelling pulse when there is none.
  */
  function link(i: number): { fill: number; color: string; pulse: boolean } {
    const s = steps[i];
    if (i < cur) return { fill: 1, color: 'bg-green-600', pulse: false };
    if (i === cur && s.state === 'active') {
      if (s.progress != null) return { fill: Math.min(100, Math.max(0, s.progress)) / 100, color: 'bg-blue-600', pulse: false };
      return { fill: 0, color: 'bg-blue-600', pulse: true };
    }
    return { fill: 0, color: 'bg-green-600', pulse: false };
  }
</script>

<div>
  <ol class="flex">
    {#each steps as s, i (s.key)}
      {@const l = link(i)}
      <li class="relative flex flex-1 justify-center">
        {#if i < steps.length - 1}
          <!-- Spans only the gap between the two nodes (radius 14px), so a percentage fills what you see. -->
          <span
            class="absolute top-3.5 left-[calc(50%+14px)] h-0.5 w-[calc(100%-28px)] overflow-hidden bg-gray-300 dark:bg-gray-600"
            aria-hidden="true"
          >
            <span class="fill absolute inset-0 origin-left {l.color}" style="transform: scaleX({l.fill})"></span>
            {#if l.pulse}<span class="pulse absolute inset-y-0 left-0 w-1/3"></span>{/if}
          </span>
        {/if}
        <button
          type="button"
          class="group relative z-10 flex flex-col items-center gap-1.5 rounded-md px-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          aria-current={sel?.key === s.key ? 'step' : undefined}
          onclick={() => (selected = s.key)}
        >
          <span
            class="node flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold {node[s.state]} {sel?.key !== s.key
              ? 'group-hover:brightness-110'
              : ''}"
          >
            {#if s.state === 'done' || s.state === 'skipped'}
              <span class="inline-flex {armed ? 'pop' : ''}"><CheckOutline class="h-4 w-4" strokeWidth="3" aria-hidden="true" /></span>
            {:else if s.state === 'failed'}
              <span class="inline-flex {armed ? 'pop' : ''}"><CloseOutline class="h-4 w-4" strokeWidth="3" aria-hidden="true" /></span>
            {:else if s.state === 'waiting'}
              <span class="inline-flex {armed ? 'pop' : ''}"><ExclamationCircleOutline class="h-4 w-4" strokeWidth="2.5" aria-hidden="true" /></span>
            {:else if s.state === 'active'}
              {i + 1}
            {/if}
          </span>
          <span
            class="text-xs whitespace-nowrap {sel?.key === s.key
              ? 'font-semibold text-gray-900 dark:text-white'
              : `max-sm:sr-only group-hover:text-gray-900 dark:group-hover:text-white ${s.state === 'pending' ? 'text-gray-500 dark:text-gray-400' : 'text-gray-700 dark:text-gray-200'}`}"
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

<style>
  .pulse {
    background: linear-gradient(90deg, transparent, var(--color-blue-500), transparent);
    transform: translateX(-100%);
  }
  /* All motion lives here, so reduced motion needs no overrides: the pulse stays parked
     off the line and the fill jumps. */
  @media (prefers-reduced-motion: no-preference) {
    .node {
      transition:
        background-color 0.4s ease,
        box-shadow 0.4s ease,
        filter 0.15s ease;
    }
    /* About as long as the gap between progress events, so updates read as one steady fill. */
    .fill {
      transition:
        transform 1s linear,
        background-color 0.4s ease;
    }
    .pulse {
      animation: haul 1.8s cubic-bezier(0.45, 0, 0.55, 1) infinite;
    }
    .pop {
      animation: pop 0.45s cubic-bezier(0.16, 1, 0.3, 1);
    }
  }
  @keyframes haul {
    to {
      transform: translateX(300%);
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.3);
      opacity: 0;
    }
  }
</style>

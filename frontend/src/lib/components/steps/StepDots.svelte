<script lang="ts">
  import { currentIndex, type Step } from './types';

  let { steps }: { steps: Step[] } = $props();

  const cur = $derived(currentIndex(steps));

  const fill: Record<Step['state'], string> = {
    done: 'bg-green-600',
    skipped: 'bg-green-600',
    active: 'bg-blue-600',
    waiting: 'bg-amber-600',
    failed: 'bg-red-600',
    pending: 'bg-gray-400 dark:bg-gray-500',
  };
  const idle = 'bg-gray-300 dark:bg-gray-600';
</script>

<!--
  Two stacked copies of the same layout. The back one draws the colored shapes
  through a "goo" filter (blur + alpha threshold) so dots, line and pill melt
  into one blob; the front one carries the crisp text, which a blur would ruin.
  Size changes are CSS transitions, so moving to the next stage animates.
-->
{#snippet track(front: boolean)}
  <!-- relative on the front: the filter makes the back a stacking context that would paint over it -->
  <span class="col-start-1 row-start-1 flex items-center {front ? 'relative' : ''}" aria-hidden={!front} style={front ? '' : 'filter: url(#steps-goo)'}>
    {#each steps as s, i (s.key)}
      {#if i > 0}
        <span class="h-1 w-3 shrink-0 transition-colors duration-500 {front ? '' : i <= cur ? fill[steps[i - 1].state] : idle}"></span>
      {/if}
      <span
        class="step {i === cur ? 'cur' : ''} {front ? 'text-white' : `text-transparent ${fill[s.state]}`}"
        title={front && i !== cur ? `${s.label}: ${s.state}` : undefined}
      >
        <span class="label">{s.label}</span>
        {#if i === cur && s.state === 'active' && s.progress != null}
          <span class="label h-1 w-10 shrink-0 overflow-hidden rounded {front ? 'bg-white/35' : ''}">
            <span class="block h-full transition-[width] duration-700 {front ? 'bg-white' : ''}" style="width: {s.progress}%"></span>
          </span>
        {/if}
      </span>
    {/each}
  </span>
{/snippet}

<span class="inline-grid whitespace-nowrap">
  {@render track(false)}
  {@render track(true)}
</span>

<svg width="0" height="0" class="absolute" aria-hidden="true">
  <filter id="steps-goo" x="-20%" y="-60%" width="140%" height="220%" color-interpolation-filters="sRGB">
    <feGaussianBlur in="SourceGraphic" stdDeviation="1.5" result="blur" />
    <feColorMatrix in="blur" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 16 -6" result="goo" />
    <feComposite in="SourceGraphic" in2="goo" operator="atop" />
  </filter>
</svg>

<style>
  .step {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    gap: 0.375rem;
    overflow: hidden;
    border-radius: 9999px;
    height: 0.625rem;
    min-width: 0.625rem;
    max-width: 0.625rem;
    padding: 0;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1;
    transition:
      max-width 0.5s ease,
      height 0.4s ease,
      padding 0.4s ease,
      background-color 0.5s ease;
  }
  .step.cur {
    height: 1.25rem;
    max-width: 10rem;
    padding: 0 0.625rem;
  }
  .label {
    opacity: 0;
    transition: opacity 0.2s ease;
  }
  .cur .label {
    opacity: 1;
    transition-delay: 0.2s;
  }
  @media (prefers-reduced-motion: reduce) {
    .step,
    .label {
      transition: none;
    }
  }
</style>

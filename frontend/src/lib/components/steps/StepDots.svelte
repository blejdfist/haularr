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
  // With progress the pill becomes a neutral well that the front layer fills with blue: gray at 0%,
  // solid blue at 100%. Different hues (not two blues) keep the fill's front edge easy to find.
  const well = 'bg-gray-600';
  const back = (s: Step, i: number) => (i === cur && s.state === 'active' && s.progress != null ? well : fill[s.state]);
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
        class="step {i === cur ? 'cur' : ''} {front ? 'text-white' : `text-transparent ${back(s, i)}`}"
        title={front && i !== cur ? `${s.label}: ${s.state}` : undefined}
      >
        {#if front}
          {@const metered = i === cur && s.state === 'active' && s.progress != null}
          {@const finished = s.state === 'done' || s.state === 'skipped'}
          <!-- At 0% the extra 2px keeps the front-edge line from peeking in at the pill's left end. -->
          <!-- Every step keeps its fill element, so a metered stage that finishes fills up, turns green while
               it shrinks to a dot, then fades into the green dot behind it. The fill is a full-width layer slid
               in from the left (the pill clips it): a composited transform, not a width change. -->
          <!-- full: still the active stage but without a percentage (Unpack moves on from extract to move),
               so the fill completes and fades out over the solid pill instead of sliding back. -->
          {@const full = !metered && i === cur && s.state === 'active'}
          <span
            class="flow {metered ? 'metered' : finished ? 'finished' : full ? 'full' : ''}"
            style="transform: translateX({metered ? Math.min(100, Math.max(0, s.progress ?? 0)) - 100 : finished || full ? 0 : -100}%) translateX({metered && !s.progress ? '-2px' : '0px'})"
          ></span>
          {#if i === cur && s.state === 'active'}
            <!-- Sweeps the whole pill on any active stage: with a percentage it rides over the fill, without
                 one (verify, import, ...) it is the indeterminate signal that work is still going on. -->
            <span class="sheen"></span>
          {/if}
        {/if}
        <span class="label relative">{s.label}</span>
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
  /* Fixed sizes (one pill width for every label) keep the whole track the
     same width in every state, so table columns don't jump. */
  .step {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: 9999px;
    height: 0.625rem;
    width: 0.625rem;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1;
    /* Stage changes wait a beat, so a progress bar finishes filling at full width before the pill shrinks. */
    transition:
      width 0.5s ease 0.25s,
      height 0.4s ease 0.25s,
      background-color 0.5s ease 0.25s;
  }
  .step.cur {
    height: 1.25rem;
    width: 4.25rem;
  }
  .label {
    opacity: 0;
    transition: opacity 0.2s ease;
  }
  .cur .label {
    opacity: 1;
    transition-delay: 0.45s;
  }
  .flow {
    position: absolute;
    inset: 0;
    opacity: 0;
    background-color: var(--color-blue-600);
    /* A light front edge marks exactly where the progress is. */
    box-shadow: inset -2px 0 0 var(--color-blue-300);
    /* Linear and about as long as the gap between progress events, so updates read as one continuous fill.
       A stage that ends mid-glide is caught by .finished, which fills the rest before the pill shrinks. */
    transition:
      transform 1s linear,
      background-color 0.5s ease,
      box-shadow 0.3s ease,
      opacity 0.3s ease;
  }
  /* Hidden fills reset only after fading out, so they never visibly slide backwards. */
  .flow:not(.metered, .finished, .full) {
    transition:
      transform 0s 0.3s,
      opacity 0.3s ease;
  }
  .flow.metered {
    opacity: 1;
  }
  /* Fill the rest before the pill starts shrinking (0.25s), turn green alongside the shrink to a dot,
     then hand over to the dot behind. */
  .flow.finished {
    background-color: var(--color-green-600);
  }
  .flow.finished,
  .flow.full {
    /* The edge line goes as the fill reaches the end, before the pill shrinks and would drag it back. */
    box-shadow: inset 0 0 0 transparent;
    transition:
      transform 0.25s cubic-bezier(0.16, 1, 0.3, 1),
      background-color 0.5s ease 0.25s,
      box-shadow 0.1s ease 0.15s,
      opacity 0.3s ease 0.75s;
  }
  .sheen {
    position: absolute;
    inset: 0;
    width: 2.5rem;
    background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.2), transparent);
    transform: translateX(-2.5rem);
    animation: sheen 2.2s cubic-bezier(0.45, 0, 0.55, 1) infinite;
  }
  /* Translate by the pill's full width (4.25rem) so the sweep crosses all of it. */
  @keyframes sheen {
    to {
      transform: translateX(4.25rem);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .step,
    .label {
      transition: none;
    }
    .flow,
    .flow.finished,
    .flow.full,
    .flow:not(.metered, .finished, .full) {
      transition: none;
    }
    .sheen {
      display: none;
    }
  }
</style>

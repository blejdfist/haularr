<script lang="ts">
  import { Tween, prefersReducedMotion } from 'svelte/motion';
  import { cubicInOut } from 'svelte/easing';
  import { currentIndex, type Step } from './types';

  let { steps }: { steps: Step[] } = $props();
  const uid = $props.id();

  const cur = $derived(currentIndex(steps));

  const fill: Record<Step['state'], string> = {
    done: 'var(--color-green-600)',
    skipped: 'var(--color-green-600)',
    active: 'var(--color-blue-600)',
    waiting: 'var(--color-amber-600)',
    failed: 'var(--color-red-600)',
    pending: 'var(--color-gray-500)',
  };
  // With progress the pill becomes a neutral well that the HTML layer fills with blue: gray at 0%,
  // solid blue at 100%. Different hues (not two blues) keep the fill's front edge easy to find.
  const color = (s: Step, i: number) =>
    i === cur && s.state === 'active' && s.progress != null ? 'var(--color-gray-600)' : fill[s.state];

  // Geometry in px. One pill size for every label, and the two nodes that resize share an easing,
  // so the track is the same width in every state and mid-move: table columns never jump.
  const DOT = 10, PILL_W = 68, PILL_H = 20, GAP = 12, LINE = 4, H = 20;
  const Y = H / 2; // center line
  const WIDTH = $derived(PILL_W + (steps.length - 1) * (DOT + GAP));

  // Node sizes animate in JS so the outline and the HTML on top move together. The delay lets a
  // progress bar finish filling at full width before the pill shrinks.
  const size = Tween.of(() => steps.map((_, i) => (i === cur ? { w: PILL_W, h: PILL_H } : { w: DOT, h: DOT })), {
    duration: () => (prefersReducedMotion.current ? 0 : 500),
    delay: prefersReducedMotion.current ? 0 : 250,
    easing: cubicInOut,
  });
  const nodes = $derived(size.current.map((n, i) => ({ ...n, x: size.current.slice(0, i).reduce((x, m) => x + m.w + GAP, 0) })));

  const f = (v: number) => v.toFixed(2);

  /*
    Top half of the track as one outline: stadiums joined by the line, each junction a cubic neck
    that leaves the line flat and lands on the cap along the circle's tangent, so line and nodes
    read as one shape. The bottom half is the same path mirrored.
  */
  const NECK = 4; // how far along the line each neck reaches
  const K = NECK * 0.55; // handle length
  const SA = Math.sin((55 * Math.PI) / 180), CA = Math.cos((55 * Math.PI) / 180); // where the neck lands on the cap
  /** Neck on one side of a node (side -1 = left, 1 = right): line point, its handle, cap handle, cap point. */
  function neck(edge: number, cx: number, r: number, side: number) {
    const bx = cx + side * r * CA, by = Y - r * SA, lx = edge + side * NECK, ly = Y - LINE / 2;
    return {
      line: `${f(lx)},${f(ly)}`,
      lineHandle: `${f(lx - side * K)},${f(ly)}`,
      capHandle: `${f(bx + side * SA * K)},${f(by + CA * K)}`,
      cap: `${f(bx)},${f(by)}`,
    };
  }
  const half = $derived.by(() => {
    let d = '';
    nodes.forEach((n, i) => {
      const r = n.h / 2, cl = n.x + r, cr = n.x + n.w - r, arc = `A${f(r)},${f(r)} 0 0 1`;
      if (i === 0) d += `M${f(n.x)},${Y}`;
      else {
        const k = neck(n.x, cl, r, -1);
        d += ` L${k.line} C${k.lineHandle} ${k.capHandle} ${k.cap}`;
      }
      d += ` ${arc} ${f(cl)},${f(Y - r)} L${f(cr)},${f(Y - r)}`;
      if (i === nodes.length - 1) d += ` ${arc} ${f(n.x + n.w)},${Y}`;
      else {
        const k = neck(n.x + n.w, cr, r, 1);
        d += ` ${arc} ${k.cap} C${k.capHandle} ${k.lineHandle} ${k.line}`;
      }
    });
    // Close just past the center line, so the two halves overlap instead of leaving a seam.
    return `${d} L${WIDTH},${Y + 0.5} L0,${Y + 0.5} Z`;
  });

  // Each node is solid in its own color from just inside its caps; between nodes the gradient
  // blends one color into the next across the line and necks.
  const stops = $derived(
    nodes.flatMap((n, i) => [
      { at: n.x + n.h * 0.3, color: color(steps[i], i) },
      { at: n.x + n.w - n.h * 0.3, color: color(steps[i], i) },
    ]),
  );

  /*
    The HTML fill inside each node: a full-width layer slid in from the left (the node clips it).
    Every node keeps one, so that
    - metered: the active stage with a percentage fills toward it (at 0% the extra 2px keeps the
      edge line from peeking in at the left end);
    - finished: a stage that completes fills the rest, turns green while shrinking to a dot, then
      fades into the green dot of the outline;
    - full: still active but without a percentage (Unpack moves on from extract to move), so the
      fill completes and fades over the solid pill instead of sliding back.
  */
  function fillOf(s: Step, i: number): { kind: string; x: string } {
    const active = i === cur && s.state === 'active';
    if (active && s.progress != null) {
      const p = Math.min(100, Math.max(0, s.progress));
      return { kind: 'metered', x: p ? `${p - 100}%` : 'calc(-100% - 2px)' };
    }
    if (s.state === 'done' || s.state === 'skipped') return { kind: 'finished', x: '0%' };
    if (active) return { kind: 'full', x: '0%' };
    return { kind: '', x: '-100%' };
  }
</script>

<span class="inline-grid whitespace-nowrap" style="--pill-w: {PILL_W}px">
  <svg class="col-start-1 row-start-1" width={WIDTH} height={H} viewBox="0 0 {WIDTH} {H}" aria-hidden="true">
    <defs>
      <linearGradient id="{uid}-c" gradientUnits="userSpaceOnUse" x1="0" x2={WIDTH} y1="0" y2="0">
        {#each stops as st, k (k)}
          <stop offset={st.at / WIDTH} style="stop-color: {st.color}" />
        {/each}
      </linearGradient>
      <path id="{uid}-h" d={half} />
    </defs>
    <use href="#{uid}-h" fill="url(#{uid}-c)" />
    <use href="#{uid}-h" fill="url(#{uid}-c)" transform="translate(0 {H}) scale(1 -1)" />
  </svg>

  <!-- HTML on top of the outline: labels, progress fill and sheen, sized from the same tween. -->
  <span class="relative col-start-1 row-start-1 flex items-center" style="gap: {GAP}px">
    {#each steps as s, i (s.key)}
      {@const fl = fillOf(s, i)}
      <span
        class="step {i === cur ? 'cur' : ''}"
        style="width: {f(nodes[i].w)}px; height: {f(nodes[i].h)}px"
        title={i !== cur ? `${s.label}: ${s.state}` : undefined}
      >
        <span class="flow {fl.kind}" style="transform: translateX({fl.x})"></span>
        {#if i === cur && s.state === 'active'}
          <!-- Any active stage shimmers: over the fill when there is a percentage, and as the
               indeterminate signal when there is none (verify, import, ...). -->
          <span class="sheen"></span>
        {/if}
        <span class="label">{s.label}</span>
      </span>
    {/each}
  </span>
</span>

<style>
  .step {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: 9999px;
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1;
  }
  .label {
    position: relative;
    opacity: 0;
  }
  .cur .label {
    opacity: 1;
  }
  .flow {
    position: absolute;
    inset: 0;
    opacity: 0;
    background-color: var(--color-blue-600);
    /* A light front edge marks exactly where the progress is. */
    box-shadow: inset -2px 0 0 var(--color-blue-300);
  }
  .flow.metered {
    opacity: 1;
  }
  .flow.finished {
    background-color: var(--color-green-600);
  }
  .flow.finished,
  .flow.full {
    box-shadow: inset 0 0 0 transparent;
  }
  .sheen {
    position: absolute;
    inset: 0;
    width: 2.5rem;
    background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.2), transparent);
    transform: translateX(-2.5rem); /* parked outside the pill; the animation sweeps it across */
  }

  /* All motion lives here, so reduced motion needs no overrides. */
  @media (prefers-reduced-motion: no-preference) {
    stop {
      transition: stop-color 0.5s ease 0.25s;
    }
    .label {
      transition: opacity 0.2s ease;
    }
    .cur .label {
      transition-delay: 0.45s;
    }
    /* Linear and about as long as the gap between progress events, so updates read as one
       continuous fill. A stage that ends mid-glide is caught by .finished. */
    .flow {
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
    /* Fill the rest and drop the edge line before the pill starts shrinking (0.25s), turn green
       alongside the shrink, then hand over to the outline's dot. */
    .flow.finished,
    .flow.full {
      transition:
        transform 0.25s cubic-bezier(0.16, 1, 0.3, 1),
        background-color 0.5s ease 0.25s,
        box-shadow 0.1s ease 0.15s,
        opacity 0.3s ease 0.75s;
    }
    .sheen {
      animation: sheen 2.2s cubic-bezier(0.45, 0, 0.55, 1) infinite;
    }
  }
  @keyframes sheen {
    to {
      transform: translateX(var(--pill-w));
    }
  }
</style>

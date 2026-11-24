<script lang="ts">
  import { ChevronRightOutline } from 'flowbite-svelte-icons';
  import { parseUtc } from '$lib/status';

  let { events }: { events: any[] } = $props();

  /** Event time: clock time today, date and time otherwise. The full stamp is in the tooltip. */
  function when(s: string): string {
    const d = parseUtc(s);
    const today = d.toDateString() === new Date().toDateString();
    return d.toLocaleString(undefined, today ? { hour: '2-digit', minute: '2-digit' } : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  const hasDetails = (d: unknown) => d != null && (typeof d !== 'object' || Object.keys(d).length > 0);
</script>

<details class="group border-t border-gray-200 pt-4 dark:border-gray-700">
  <summary
    class="flex cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-semibold text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 dark:text-white [&::-webkit-details-marker]:hidden"
  >
    <ChevronRightOutline
      class="h-4 w-4 text-gray-500 transition-transform group-open:rotate-90 motion-reduce:transition-none dark:text-gray-400"
      aria-hidden="true"
    />
    Events
    <span class="font-normal text-gray-500 tabular-nums dark:text-gray-400">{events.length}</span>
  </summary>
  {#if events.length}
    <!-- A timeline: one rail, a dot per event colored by severity. -->
    <ol class="mt-3 ms-2 border-s border-gray-200 text-sm dark:border-gray-700">
      {#each events as e}
        <li class="relative ps-4 pb-3 last:pb-0">
          <span
            class="absolute -start-1 top-1.5 h-2 w-2 rounded-full ring-4 ring-white dark:ring-gray-800 {e.severity === 'error'
              ? 'bg-red-500'
              : e.severity === 'warning'
                ? 'bg-amber-500'
                : 'bg-gray-400 dark:bg-gray-500'}"
          ></span>
          <time class="block text-xs text-gray-500 tabular-nums dark:text-gray-400" datetime={e.created_at} title={parseUtc(e.created_at).toLocaleString()}
            >{when(e.created_at)}</time
          >
          <p class="break-words {e.severity === 'error' ? 'text-red-700 dark:text-red-300' : 'text-gray-800 dark:text-gray-100'}" title={e.kind}>{e.message}</p>
          {#if e.severity === 'error' && hasDetails(e.details)}
            <pre class="mt-1 overflow-x-auto rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap text-gray-700 dark:bg-gray-900/40 dark:text-gray-300">{JSON.stringify(e.details, null, 2)}</pre>
          {/if}
        </li>
      {/each}
    </ol>
  {:else}
    <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Nothing logged yet.</p>
  {/if}
</details>

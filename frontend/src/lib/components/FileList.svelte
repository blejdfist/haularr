<script lang="ts">
  import { FolderSolid } from 'flowbite-svelte-icons';
  import StatusIcon from '$lib/components/StatusIcon.svelte';
  import { commonRoot, type List } from '$lib/stages';

  let { list }: { list: List } = $props();

  const root = $derived(commonRoot(list.rows.map((f) => f.path)));
</script>

<div class="mt-1.5 ms-6 text-xs">
  {#each list.caption as line}
    <p class="mb-1 truncate text-gray-600 dark:text-gray-300" title={line}>{line}</p>
  {/each}
  {#if list.rows.length}
    <ul class="divide-y divide-gray-200 overflow-hidden rounded-md border border-gray-200 bg-white dark:divide-gray-700 dark:border-gray-700 dark:bg-gray-800">
      {#if root}
        <!-- The release folder every file sits in, as the list's header. -->
        <li class="flex items-center gap-2 bg-gray-50 px-2.5 py-1.5 text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
          <FolderSolid class="h-3.5 w-3.5 shrink-0 text-gray-400 dark:text-gray-500" aria-hidden="true" />
          <span class="min-w-0 truncate" title={root.slice(0, -1)}>{root.slice(0, -1)}</span>
        </li>
      {/if}
      {#each list.rows as f (f.key)}
        {@const rel = f.path.slice(root.length)}
        {@const slash = rel.lastIndexOf('/')}
        <li class="flex items-start gap-2 px-2.5 py-1.5">
          <StatusIcon kind={f.kind} class="mt-px h-3.5 w-3.5 shrink-0" />
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2">
              <!-- Folder and name on one line; a long folder shrinks before the name does. -->
              <span class="flex min-w-0 flex-1 text-gray-900 dark:text-white" title={f.path}>
                {#if slash > 0}<span class="min-w-0 shrink-[999] truncate text-gray-500 dark:text-gray-400"
                    >{rel.slice(0, slash + 1)}</span
                  >{/if}<span class="min-w-0 truncate">{rel.slice(slash + 1)}</span>
              </span>
              {#if f.meta}<span class="whitespace-nowrap text-gray-600 tabular-nums dark:text-gray-300">{f.meta}</span>{/if}
            </div>
            {#if f.pct != null}
              <div class="mt-1 h-1 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
                <div class="h-full bg-blue-600 transition-[width] duration-700" style="width: {f.pct}%"></div>
              </div>
            {/if}
            {#if f.note}
              <p class={f.tone === 'error' ? 'text-red-700 dark:text-red-300' : f.tone === 'warn' ? 'text-amber-700 dark:text-amber-300' : 'text-gray-500 dark:text-gray-400'}>
                {f.note}
              </p>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {:else if list.empty}
    <p class="text-gray-500 dark:text-gray-400">{list.empty}</p>
  {/if}
</div>

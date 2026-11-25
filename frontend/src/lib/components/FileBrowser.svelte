<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { Button, Input } from 'flowbite-svelte';
  import {
    ArrowUpOutline,
    ChevronRightOutline,
    ExclamationCircleOutline,
    FolderOpenOutline,
    FolderOutline,
    PenOutline,
    SearchOutline,
    ServerOutline,
  } from 'flowbite-svelte-icons';
  import { endpoints, type DirectoryListing } from '$lib/api/client';
  import { crumbs } from '$lib/paths';

  let {
    initialPath = '',
    onselect,
    oncancel,
  }: {
    initialPath?: string;
    onselect: (path: string) => void;
    oncancel: () => void;
  } = $props();

  /** Folder count from which a filter box earns its row. */
  const FILTER_FROM = 9;
  const CRUMB =
    'flex h-10 items-center rounded-lg px-2 text-gray-600 transition-colors hover:bg-gray-200 hover:text-gray-900 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-500 aria-[current]:font-semibold aria-[current]:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white dark:aria-[current]:text-white';

  const uid = $props.id();
  let listing = $state<DirectoryListing | null>(null);
  let busy = $state(false);
  let error = $state('');
  let editing = $state(false);
  let draft = $state('');
  let filter = $state('');
  let cameFrom = $state('');
  let direction = $state<'in' | 'out'>('in');
  let root: HTMLElement;
  let list = $state<HTMLElement>();
  let trail = $state<HTMLElement>();
  let request = 0;

  const here = $derived(crumbs(listing?.path ?? ''));
  const folders = $derived(listing?.directories ?? []);
  const shown = $derived(
    folders.filter((d) => d.name.toLowerCase().includes(filter.trim().toLowerCase())),
  );
  const selectable = $derived(!busy && !error && !!listing?.path);

  async function browse(path: string) {
    const current = ++request;
    const hadFocus = root.contains(document.activeElement);
    busy = true;
    error = '';
    try {
      const result = await endpoints.filesystem.browse(path);
      if (current !== request) return false;
      const before = here;
      const after = crumbs(result.path ?? '');
      // Going up: mark the folder we just left, so the eye lands where it was.
      const at = result.path ? before.findIndex((c) => c.path === result.path) : -1;
      cameFrom = (result.path ? (at < 0 ? '' : before[at + 1]?.path) : before[0]?.path) ?? '';
      direction = after.length < before.length ? 'out' : 'in';
      listing = result;
      filter = '';
      editing = false;
      await tick();
      trail?.scrollTo({ left: trail.scrollWidth });
      const rows = list?.querySelectorAll<HTMLButtonElement>('[data-path]');
      const target = [...(rows ?? [])].find((r) => r.dataset.path === cameFrom);
      target?.scrollIntoView({ block: 'nearest' });
      // The focused row is gone after a move; keep keyboard users inside the list.
      if (hadFocus && !root.contains(document.activeElement)) (target ?? rows?.[0] ?? list)?.focus();
      return true;
    } catch (e) {
      if (current !== request) return false;
      error = e instanceof Error ? e.message : 'Unable to browse folders. Try another path.';
      return false;
    } finally {
      if (current === request) busy = false;
    }
  }

  function edit() {
    draft = listing?.path ?? '';
    editing = true;
  }

  function stopEditing() {
    editing = false;
    error = '';
  }

  const up = () => {
    if (listing?.path) void browse(listing.parent ?? '');
  };

  function focusAndSelect(node: HTMLInputElement) {
    node.focus();
    node.select();
  }

  function listKeys(event: KeyboardEvent) {
    if (event.target instanceof HTMLInputElement) return;
    const rows = [...(list?.querySelectorAll<HTMLButtonElement>('[data-path]') ?? [])];
    const i = rows.indexOf(document.activeElement as HTMLButtonElement);
    const to = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: rows.length - 1 }[event.key];
    if (to !== undefined) rows[Math.max(0, Math.min(to, rows.length - 1))]?.focus();
    else if (event.key === 'ArrowRight' && i >= 0) rows[i].click();
    else if (event.key === 'ArrowLeft' || event.key === 'Backspace') up();
    else return;
    event.preventDefault();
  }

  onMount(() => {
    void (async () => {
      if (await browse(initialPath)) return;
      if (!initialPath) return;
      // A saved folder that no longer opens: show the roots, keep the path ready to fix.
      const failed = error;
      if (await browse('')) {
        error = failed;
        draft = initialPath;
        editing = true;
      }
    })();
    return () => { request++; };
  });
</script>

{#snippet iconButton(label: string, Icon: typeof PenOutline, onclick: () => void, disabled = false, pressed?: boolean)}
  <button type="button" {disabled} {onclick} aria-label={label} title={label} aria-pressed={pressed}
    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-2 focus-visible:outline-primary-500 disabled:pointer-events-none disabled:opacity-40 aria-pressed:bg-gray-200 aria-pressed:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white dark:aria-pressed:bg-gray-700 dark:aria-pressed:text-white">
    <Icon class="h-4 w-4" aria-hidden="true" />
  </button>
{/snippet}

<div bind:this={root} class="flex flex-col gap-3">
  <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
    <!-- Address bar: one place that says where you are, and takes a typed path. -->
    <div class="flex items-center gap-1 border-b border-gray-200 bg-gray-50 p-1 dark:border-gray-700 dark:bg-gray-900/40">
      {@render iconButton('Up one folder', ArrowUpOutline, up, !listing?.path)}
      {#if editing}
        <input
          use:focusAndSelect
          bind:value={draft}
          aria-label="Server folder path"
          aria-describedby={error ? `${uid}-error` : undefined}
          aria-invalid={!!error}
          placeholder="Absolute path on the Haularr server"
          spellcheck="false"
          autocomplete="off"
          class="h-10 min-w-0 flex-1 rounded-lg border-gray-300 bg-white text-sm text-gray-900 caret-primary-500 focus:border-primary-500 focus:ring-primary-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          onkeydown={(event) => {
            if (event.key !== 'Enter' && event.key !== 'Escape') return;
            // Neither key may reach the surrounding dialog or form.
            event.preventDefault();
            event.stopPropagation();
            if (event.key === 'Enter') void browse(draft.trim());
            else stopEditing();
          }}
        />
        <Button type="button" color="alternative" class="h-10" onclick={() => browse(draft.trim())}>Go</Button>
      {:else}
        <nav bind:this={trail} aria-label="Folder path" class="min-w-0 flex-1 overflow-x-auto [scrollbar-width:none]">
          <ol class="flex w-max items-center text-sm whitespace-nowrap">
            <li>
              <button type="button" onclick={() => browse('')} aria-current={here.length ? undefined : 'location'}
                class="{CRUMB} gap-2">
                <ServerOutline class="h-4 w-4" aria-hidden="true" />
                <span class={here.length ? 'sr-only' : ''}>Haularr server</span>
              </button>
            </li>
            {#each here as c, i (c.path)}
              <li class="flex items-center">
                <ChevronRightOutline class="h-3 w-3 text-gray-400 dark:text-gray-500" aria-hidden="true" />
                <button type="button" class={CRUMB} title={c.path} onclick={() => browse(c.path)}
                  aria-current={i === here.length - 1 ? 'location' : undefined}>{c.name}</button>
              </li>
            {/each}
          </ol>
        </nav>
      {/if}
      {@render iconButton('Type a path', PenOutline, () => (editing ? stopEditing() : edit()), false, editing)}
    </div>

    <div class="relative flex h-[min(22rem,50dvh)] flex-col bg-white dark:bg-gray-800">
      {#if busy}
        <!-- Delayed, so a quick folder change never flashes. -->
        <div role="status" class="loading absolute inset-x-0 top-0 z-10 h-0.5 bg-primary-500">
          <span class="sr-only">Loading folders…</span>
        </div>
      {/if}

      {#if error}
        <p id={`${uid}-error`} role="alert"
          class="flex items-start gap-2 border-b border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <ExclamationCircleOutline class="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="min-w-0 break-words">{error}</span>
        </p>
      {/if}

      {#if folders.length >= FILTER_FROM}
        <div class="border-b border-gray-200 p-2 dark:border-gray-700">
          <Input type="search" size="sm" class="ps-9" bind:value={filter} aria-label="Filter folders"
            placeholder={`Filter ${folders.length} folders`} autocomplete="off"
            onkeydown={(event: KeyboardEvent) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                if (shown[0]) void browse(shown[0].path);
              } else if (event.key === 'ArrowDown') {
                event.preventDefault();
                list?.querySelector<HTMLButtonElement>('[data-path]')?.focus();
              }
            }}>
            {#snippet left()}<SearchOutline class="h-4 w-4" aria-hidden="true" />{/snippet}
          </Input>
        </div>
      {/if}

      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div bind:this={list} role="group" aria-label="Folders" aria-busy={busy} tabindex="-1" onkeydown={listKeys}
        class="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-1 outline-none transition-opacity {busy ? 'opacity-60 delay-200' : ''}">
        {#if !listing}
          {#if busy}
            {#each [55, 40, 65, 35, 50] as width}
              <div class="flex h-10 items-center gap-3 px-3" aria-hidden="true">
                <div class="h-5 w-5 rounded bg-gray-200 motion-safe:animate-pulse dark:bg-gray-700"></div>
                <div class="h-3 rounded bg-gray-200 motion-safe:animate-pulse dark:bg-gray-700" style="width: {width}%"></div>
              </div>
            {/each}
          {/if}
        {:else}
          {#key listing}
            <ul class="enter-{direction}">
              {#each shown as directory (directory.path)}
                <li>
                  <button type="button" data-path={directory.path} onclick={() => browse(directory.path)}
                    class="group flex min-h-10 w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-500 {directory.path === cameFrom
                      ? 'bg-primary-50 dark:bg-primary-500/15'
                      : 'hover:bg-gray-100 dark:hover:bg-gray-700'}">
                    <span class="shrink-0 text-gray-500 group-hover:text-primary-600 group-focus-visible:text-primary-600 dark:text-gray-400 dark:group-hover:text-primary-400 dark:group-focus-visible:text-primary-400" aria-hidden="true">
                      <FolderOutline class="h-5 w-5 group-hover:hidden group-focus-visible:hidden" />
                      <FolderOpenOutline class="hidden h-5 w-5 group-hover:block group-focus-visible:block" />
                    </span>
                    <span class="min-w-0 flex-1 break-all text-gray-900 dark:text-white">{directory.name}</span>
                    <ChevronRightOutline class="h-3.5 w-3.5 shrink-0 -translate-x-1 text-gray-500 opacity-0 transition group-hover:translate-x-0 group-hover:opacity-100 group-focus-visible:translate-x-0 group-focus-visible:opacity-100 motion-reduce:transition-none dark:text-gray-400" aria-hidden="true" />
                  </button>
                </li>
              {/each}
            </ul>
            {#if !shown.length}
              <div class="enter-{direction} flex flex-col items-center gap-2 px-6 py-12 text-center text-sm text-gray-600 dark:text-gray-300">
                {#if filter}
                  <p class="break-all">No folder matches “{filter}”.</p>
                  <Button type="button" size="xs" color="alternative" onclick={() => (filter = '')}>Clear filter</Button>
                {:else}
                  <FolderOpenOutline class="h-8 w-8 text-gray-400 dark:text-gray-500" aria-hidden="true" />
                  <p class="font-medium text-gray-900 dark:text-white">No subfolders here</p>
                  {#if listing.path}<p>This is the end of the trail. You can still select this folder.</p>{/if}
                {/if}
              </div>
            {/if}
          {/key}
        {/if}
      </div>
    </div>
  </div>

  <p class="sr-only" aria-live="polite">{listing?.path ?? 'Haularr server'}</p>

  <div class="flex flex-wrap items-center justify-end gap-2">
    <p class="me-auto text-sm text-gray-600 dark:text-gray-300">
      {listing?.path ? 'On the Haularr server' : 'Open a location to select it'}
    </p>
    <Button type="button" color="alternative" onclick={oncancel}>Cancel</Button>
    <Button type="button" class="max-w-full" disabled={!selectable}
      onclick={() => { if (listing?.path) onselect(listing.path); }}>
      <span class="max-w-56 truncate">{here.length ? `Select “${here[here.length - 1].name}”` : 'Select folder'}</span>
    </Button>
  </div>
</div>

<style>
  /* Deeper slides in from the right, back out from the left. */
  .enter-in {
    animation: enter 220ms cubic-bezier(0.16, 1, 0.3, 1);
    --from: 1rem;
  }
  .enter-out {
    animation: enter 220ms cubic-bezier(0.16, 1, 0.3, 1);
    --from: -1rem;
  }
  @keyframes enter {
    from {
      opacity: 0.3;
      transform: translateX(var(--from));
    }
  }
  .loading {
    transform-origin: left;
    animation: loading 6s cubic-bezier(0.16, 1, 0.3, 1) 200ms both;
  }
  @keyframes loading {
    from {
      transform: scaleX(0);
    }
    to {
      transform: scaleX(0.92);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .enter-in,
    .enter-out {
      animation: none;
    }
    .loading {
      animation-duration: 1ms;
    }
  }
</style>

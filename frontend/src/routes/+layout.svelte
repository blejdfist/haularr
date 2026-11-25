<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { endpoints, getAuthToken, setAuthToken } from '$lib/api/client';
  import { groupCount } from '$lib/status';
  import { subscribe, coalesce, type JobEvent } from '$lib/live';
  import logo from '$lib/assets/logo.png?enhanced';
  import {
    BarsOutline,
    ChartPieOutline,
    CogOutline,
    DatabaseOutline,
    FileLinesOutline,
    ServerOutline,
    ArrowRightToBracketOutline,
    MoonOutline,
    SunOutline,
  } from 'flowbite-svelte-icons';

  let { children } = $props();

  const links = [
    { href: '/', label: 'Dashboard', icon: ChartPieOutline },
    { href: '/sources/', label: 'Sources', icon: ServerOutline },
    { href: '/libraries/', label: 'Libraries', icon: DatabaseOutline },
    { href: '/logs/', label: 'Logs', icon: FileLinesOutline },
    { href: '/settings/', label: 'Settings', icon: CogOutline },
  ];

  const path = $derived(page.url.pathname);
  const onLogin = $derived(path.startsWith('/login'));
  let menuOpen = $state(false);

  $effect(() => {
    if (!onLogin && !getAuthToken()) goto('/login/');
  });

  // Close the mobile menu after navigating
  $effect(() => {
    path;
    menuOpen = false;
  });

  // app.html sets the class before paint; this mirrors it and saves changes.
  let dark = $state(typeof document === 'undefined' || document.documentElement.classList.contains('dark'));
  function applyTheme() {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light');
    } catch {
      /* storage unavailable: the choice lasts this page view */
    }
  }

  function logout() {
    setAuthToken(null);
    goto('/login/');
  }

  const isActive = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
  const current = $derived(links.findIndex((l) => isActive(l.href)));

  // Job counts for the menu, so running and failed work shows from any page. Refetched when a
  // job's status or stage changes; progress ticks alone don't change the counts.
  let by = $state<Record<string, number>>({});
  const active = $derived(groupCount(by, 'active'));
  const failed = $derived(groupCount(by, 'failed'));

  $effect(() => {
    if (onLogin || !getAuthToken()) return;
    const seen = new Map<string, string>();
    const refetch = coalesce(async () => {
      try {
        by = (await endpoints.dashboard.get()).jobs?.by_status ?? {};
      } catch {
        /* counts are a hint; the pages show their own errors */
      }
    });
    return subscribe('/events/jobs', {
      open: refetch,
      job: (e: JobEvent) => {
        const k = `${e.status}|${e.stage}`;
        if (seen.get(e.id) !== k) {
          seen.set(e.id, k);
          refetch();
        }
      },
    });
  });
</script>

<svelte:head><title>Haularr</title></svelte:head>

{#if onLogin}
  <main class="mx-auto max-w-7xl p-4">{@render children()}</main>
{:else}
  <!-- Mobile top bar -->
  <header class="flex items-center gap-3 border-b border-gray-200 dark:border-gray-800 bg-gray-100 dark:bg-gray-950 px-4 py-2 lg:hidden">
    <button
      class="rounded-lg p-2 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800"
      aria-label="Open menu"
      aria-expanded={menuOpen}
      onclick={() => (menuOpen = true)}
    >
      <BarsOutline class="h-6 w-6" />
    </button>
    <a href="/" aria-label="Haularr home"><enhanced:img src={logo} alt="Haularr" class="h-8 w-auto" sizes="120px" /></a>
    {#if failed}
      <a href="/?f=failed" class="ml-auto rounded-full bg-red-500/15 px-2.5 py-1 text-xs font-medium text-red-600 dark:text-red-400 tabular-nums">
        {failed} failed
      </a>
    {/if}
  </header>

  {#if menuOpen}
    <button class="fixed inset-0 z-30 bg-black/50 lg:hidden" aria-label="Close menu" onclick={() => (menuOpen = false)}></button>
  {/if}

  <aside
    class="fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-100 dark:bg-gray-950 transition-transform lg:translate-x-0 {menuOpen
      ? 'translate-x-0'
      : '-translate-x-full'}"
  >
    <a href="/" class="block px-5 py-5" aria-label="Haularr home">
      <enhanced:img src={logo} alt="Haularr" class="h-auto w-full" sizes="200px" />
    </a>
    <nav class="relative flex-1 px-3">
      <!-- One highlight that glides to the current page (items are h-10 + space-y-1 = 44px apart). -->
      {#if current >= 0}
        <span
          aria-hidden="true"
          class="absolute inset-x-3 top-0 h-10 rounded-lg bg-gray-200 dark:bg-gray-800 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
          style="transform: translateY({current * 44}px)"
        ></span>
      {/if}
      <div class="relative space-y-1">
        {#each links as l, i}
          <a
            href={l.href}
            aria-current={i === current ? 'page' : undefined}
            class="flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors duration-150 hover:bg-gray-200/50 dark:hover:bg-gray-800/50 hover:text-gray-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:outline-none {i ===
            current
              ? 'text-gray-900 dark:text-white'
              : 'text-gray-600 dark:text-gray-400'}"
          >
            <l.icon class="h-5 w-5 transition-colors duration-300 {i === current ? 'text-primary-500' : ''}" />{l.label}
            {#if l.href === '/' && (active || failed)}
              <span class="ml-auto flex gap-1 text-xs tabular-nums">
                {#if active}<span class="rounded-full bg-blue-500/15 px-2 py-0.5 text-blue-700 dark:text-blue-300" title="{active} active">{active}</span>{/if}
                {#if failed}<span class="rounded-full bg-red-500/15 px-2 py-0.5 text-red-600 dark:text-red-400" title="{failed} failed">{failed}</span>{/if}
              </span>
            {/if}
          </a>
        {/each}
      </div>
    </nav>
    <!-- Utility footer: one quiet row under a hairline, so it doesn't compete with the nav. -->
    <div class="m-3 flex items-center gap-2 border-t border-gray-200 pt-3 dark:border-gray-800">
      <button
        class="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-200 hover:text-gray-900 focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:outline-none dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white"
        onclick={logout}
      >
        <ArrowRightToBracketOutline class="h-5 w-5" />Log out
      </button>
      <!-- Sun/moon pill: the knob sits under the active theme. -->
      <button
        type="button"
        role="switch"
        aria-checked={dark}
        aria-label="Dark mode"
        title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
        onclick={() => {
          dark = !dark;
          applyTheme();
        }}
        class="group relative grid h-7 w-14 shrink-0 before:absolute before:-inset-1.5 grid-cols-2 items-center rounded-full bg-gray-200 p-0.5 transition-colors duration-150 hover:bg-gray-300 focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-100 focus-visible:outline-none dark:bg-gray-800 dark:hover:bg-gray-700 dark:focus-visible:ring-offset-gray-950"
      >
        <span
          aria-hidden="true"
          class="absolute inset-y-0.5 left-0.5 w-[calc(50%-0.125rem)] rounded-full bg-white shadow-xs transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none dark:bg-gray-600 {dark
            ? 'translate-x-full'
            : ''}"
        ></span>
        <!-- Active icon is orange; the other darkens on hover to hint where a click goes. -->
        <SunOutline
          class="relative mx-auto h-4 w-4 transition-colors duration-300 {dark
            ? 'text-gray-400 group-hover:text-gray-200'
            : 'text-primary-600'}"
        />
        <MoonOutline
          class="relative mx-auto h-4 w-4 transition-colors duration-300 {dark
            ? 'text-primary-400'
            : 'text-gray-500 group-hover:text-gray-800'}"
        />
      </button>
    </div>
  </aside>

  <main class="p-4 lg:ml-60 lg:p-6">
    <div class="mx-auto max-w-7xl">{@render children()}</div>
  </main>
{/if}

<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { getAuthToken, setAuthToken } from '$lib/api/client';
  import logo from '$lib/assets/logo.png?enhanced';
  import {
    BarsOutline,
    ChartPieOutline,
    CogOutline,
    DatabaseOutline,
    FileLinesOutline,
    ServerOutline,
    ArrowRightToBracketOutline,
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

  function logout() {
    setAuthToken(null);
    goto('/login/');
  }

  const isActive = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
</script>

<svelte:head><title>Haularr</title></svelte:head>

{#if onLogin}
  <main class="mx-auto max-w-7xl p-4">{@render children()}</main>
{:else}
  <!-- Mobile top bar -->
  <header class="flex items-center gap-3 border-b border-gray-800 bg-gray-950 px-4 py-2 lg:hidden">
    <button
      class="rounded-lg p-2 text-gray-300 hover:bg-gray-800"
      aria-label="Open menu"
      aria-expanded={menuOpen}
      onclick={() => (menuOpen = true)}
    >
      <BarsOutline class="h-6 w-6" />
    </button>
    <a href="/" aria-label="Haularr home"><enhanced:img src={logo} alt="Haularr" class="h-8 w-auto" sizes="120px" /></a>
  </header>

  {#if menuOpen}
    <button class="fixed inset-0 z-30 bg-black/50 lg:hidden" aria-label="Close menu" onclick={() => (menuOpen = false)}></button>
  {/if}

  <aside
    class="fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-gray-800 bg-gray-950 transition-transform lg:translate-x-0 {menuOpen
      ? 'translate-x-0'
      : '-translate-x-full'}"
  >
    <a href="/" class="block px-5 py-5" aria-label="Haularr home">
      <enhanced:img src={logo} alt="Haularr" class="h-auto w-full" sizes="200px" />
    </a>
    <nav class="flex-1 space-y-1 px-3">
      {#each links as l}
        <a
          href={l.href}
          aria-current={isActive(l.href) ? 'page' : undefined}
          class="flex items-center gap-3 rounded-lg border-l-4 px-3 py-2 text-sm font-medium {isActive(l.href)
            ? 'border-primary-500 bg-gray-800 text-white'
            : 'border-transparent text-gray-400 hover:bg-gray-800 hover:text-white'}"
        >
          <l.icon class="h-5 w-5" />{l.label}
        </a>
      {/each}
    </nav>
    <button
      class="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-gray-400 hover:bg-gray-800 hover:text-white"
      onclick={logout}
    >
      <ArrowRightToBracketOutline class="h-5 w-5" />Log out
    </button>
  </aside>

  <main class="p-4 lg:ml-60 lg:p-6">
    <div class="mx-auto max-w-7xl">{@render children()}</div>
  </main>
{/if}

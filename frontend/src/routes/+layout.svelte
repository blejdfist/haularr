<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { getAuthToken, setAuthToken } from '$lib/api/client';
  import { Navbar, NavBrand, NavUl, NavLi, NavHamburger } from 'flowbite-svelte';
  import { CogOutline } from 'flowbite-svelte-icons';

  let { children } = $props();

  const links = [
    { href: '/', label: 'Dashboard' },
    { href: '/sources/', label: 'Sources' },
    { href: '/libraries/', label: 'Libraries' },
  ];

  const path = $derived(page.url.pathname);
  const onLogin = $derived(path.startsWith('/login'));

  $effect(() => {
    if (!onLogin && !getAuthToken()) goto('/login/');
  });

  function logout() {
    setAuthToken(null);
    goto('/login/');
  }

  const isActive = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
</script>

{#if !onLogin}
<Navbar class="border-b border-gray-200 dark:border-gray-700">
  <NavBrand href="/">
    <span class="self-center text-xl font-semibold whitespace-nowrap">Haularr</span>
  </NavBrand>
  <NavHamburger />
  <NavUl>
    {#each links as l}
      <NavLi href={l.href}  aria-current={isActive(l.href) ? "page" : undefined} class={isActive(l.href) ? "font-semibold text-primary-700 dark:text-primary-500" : ""}>{l.label}</NavLi>
    {/each}
    <NavLi href="/settings/"  aria-current={isActive('/settings/') ? "page" : undefined} class={isActive('/settings/') ? "font-semibold text-primary-700 dark:text-primary-500" : ""} aria-label="Settings">
      <CogOutline class="h-5 w-5" />
    </NavLi>
    <NavLi href="/login/" onclick={(e: Event) => { e.preventDefault(); logout(); }}>Log out</NavLi>
  </NavUl>
</Navbar>
{/if}

<main class="mx-auto max-w-7xl p-4">
  {@render children()}
</main>

<svelte:head><title>Haularr</title></svelte:head>

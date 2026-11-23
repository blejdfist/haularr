<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { Navbar, NavBrand, NavUl, NavLi, NavHamburger } from 'flowbite-svelte';
  import { CogOutline } from 'flowbite-svelte-icons';

  let { children } = $props();

  const links = [
    { href: '/', label: 'Dashboard' },
    { href: '/sources/', label: 'Sources' },
    { href: '/libraries/', label: 'Libraries' },
  ];

  const path = $derived(page.url.pathname);
  const isActive = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
</script>

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
  </NavUl>
</Navbar>

<main class="mx-auto max-w-7xl p-4">
  {@render children()}
</main>

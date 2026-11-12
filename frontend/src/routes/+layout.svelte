<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';

  let { children } = $props();

  const navItems = [
    { href: '/', label: 'Dashboard', icon: '📊' },
    { href: '/sources', label: 'Sources', icon: '📥' },
    { href: '/inventory', label: 'Inventory', icon: '📦' },
    { href: '/jobs', label: 'Jobs', icon: '⚙️' },
    { href: '/attention', label: 'Attention', icon: '⚠️' },
    { href: '/history', label: 'History', icon: '📜' },
    { href: '/config', label: 'Config', icon: '🔧' },
  ];

  function isActive(href: string): boolean {
    if (href === '/') return $page.url.pathname === '/';
    return $page.url.pathname.startsWith(href);
  }
</script>

<div class="flex h-screen">
  <!-- Sidebar -->
  <aside class="w-64 bg-slate-900 border-r border-slate-700 flex flex-col">
    <div class="px-4 py-5 border-b border-slate-700">
      <h1 class="text-xl font-bold text-blue-400">Haularr</h1>
      <p class="text-xs text-slate-500">Download Orchestrator</p>
    </div>
    <nav class="flex-1 py-2">
      {#each navItems as item}
        <a
          href={item.href}
          class="flex items-center gap-3 px-4 py-2.5 text-sm transition-colors
            {isActive(item.href) ? 'bg-slate-700 text-blue-400 border-l-2 border-blue-400' : 'text-slate-300 hover:bg-slate-800 hover:text-slate-100'}"
        >
          <span class="text-lg">{item.icon}</span>
          <span>{item.label}</span>
        </a>
      {/each}
    </nav>
  </aside>

  <!-- Main content -->
  <main class="flex-1 overflow-auto bg-slate-950">
    {@render children()}
  </main>
</div>

<script lang="ts">
  import { Card } from 'flowbite-svelte';

  let { active, failed, done7d }: { active: number; failed: number; done7d: number } = $props();
</script>

<div class="grid grid-cols-3 gap-4">
  <Card class="max-w-none p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Active</div>
    <div class="text-3xl font-bold text-blue-600 dark:text-blue-400">{active}</div>
  </Card>
  <Card class="max-w-none p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Failed</div>
    <div class="text-3xl font-bold {failed ? 'text-red-600 dark:text-red-400' : ''}">{failed}</div>
  </Card>
  <Card class="max-w-none p-4">
    <div class="text-sm text-gray-500 dark:text-gray-400">Completed (7d)</div>
    <div class="text-3xl font-bold">{done7d}</div>
  </Card>
</div>

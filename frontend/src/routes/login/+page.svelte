<script lang="ts">
  import { goto } from '$app/navigation';
  import { Alert, Button, Card, Input, Label } from 'flowbite-svelte';
  import { endpoints, setAuthToken } from '$lib/api/client';

  let username = $state('');
  let password = $state('');
  let setup = $state(false);
  let error = $state('');
  let busy = $state(false);

  async function submit(e: Event) {
    e.preventDefault();
    busy = true;
    error = '';
    try {
      const r = await (setup ? endpoints.auth.setup : endpoints.auth.login)(username, password);
      setAuthToken(r.access_token);
      await goto('/');
    } catch (err) {
      error = (err as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="mx-auto mt-16 max-w-sm">
  <Card class="p-6">
    <h1 class="mb-4 text-xl font-bold">{setup ? 'Create admin account' : 'Sign in to Haularr'}</h1>
    {#if error}<Alert color="red" class="mb-4">{error}</Alert>{/if}
    <form onsubmit={submit} class="grid gap-4">
      <div>
        <Label for="username" class="mb-1">Username</Label>
        <Input id="username" bind:value={username} autocomplete="username" required />
      </div>
      <div>
        <Label for="password" class="mb-1">Password</Label>
        <Input id="password" type="password" bind:value={password} autocomplete={setup ? 'new-password' : 'current-password'} required />
      </div>
      <Button type="submit" disabled={busy}>{setup ? 'Create account' : 'Sign in'}</Button>
    </form>
    <button type="button" class="mt-4 text-sm text-primary-600 hover:underline" onclick={() => { setup = !setup; error = ''; }}>
      {setup ? 'Back to sign in' : 'First run? Create admin account'}
    </button>
  </Card>
</div>

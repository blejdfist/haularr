<script lang="ts">
  import { goto } from '$app/navigation';
  import { Alert, Button, Card, Input, Label } from 'flowbite-svelte';
  import { endpoints, setAuthToken } from '$lib/api/client';
  import logo from '$lib/assets/logo.png?enhanced';

  let username = $state('');
  let password = $state('');
  let setup = $state<boolean | null>(null);
  let error = $state('');
  let busy = $state(false);

  endpoints.auth.setupStatus().then(
    (r) => (setup = r.needed),
    (err) => { setup = false; error = (err as Error).message; },
  );

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
  <enhanced:img src={logo} alt="Haularr" class="mx-auto mb-8 h-auto w-64" sizes="256px" />
  {#if setup !== null}
  <Card class="p-6">
    <h1 class="mb-4 text-xl font-bold">{setup ? 'Create admin account' : 'Sign in'}</h1>
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
  </Card>
  {/if}
</div>

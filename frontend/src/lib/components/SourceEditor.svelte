<script lang="ts">
  import { Modal, Button, Input, Label, Toggle, Alert, Heading } from 'flowbite-svelte';
  import { endpoints, type Source, type Library, type FetchInput } from '$lib/api/client';
  import TagRulesTable from './TagRulesTable.svelte';

  let {
    open = $bindable(false),
    source,
    libraries,
    onsaved,
    ondeleted,
  }: { open: boolean; source: Source | null; libraries: Library[]; onsaved: () => void; ondeleted: () => void } =
    $props();

  let current = $state<Source | null>(null);
  let name = $state('');
  let host = $state('');
  let port = $state(443);
  let urlPath = $state('');
  let useTls = $state(true);
  let tlsVerify = $state(true);
  let username = $state('');
  let password = $state('');
  let pollInterval = $state(30);
  let enabled = $state(true);

  let fHost = $state('');
  let fPort = $state(21);
  let fUser = $state('');
  let fPass = $state('');
  let fVerify = $state(true);
  let fMaps = $state<{ source_prefix: string; remote_prefix: string }[]>([]);
  let fetchTouched = $state(false);

  let error = $state('');
  let testResult = $state<{ ok: boolean; text: string } | null>(null);
  let busy = $state(false);
  let confirmOpen = $state(false);
  let seenLabels = $state<string[]>([]);

  // Reset the form each time the editor opens.
  $effect(() => {
    if (!open) return;
    load(source);
  });

  function load(s: Source | null) {
    current = s;
    const c = s?.connection_config ?? {};
    name = s?.name ?? '';
    host = c.host ?? '';
    port = c.port ?? 443;
    urlPath = c.url_path ?? '';
    useTls = c.use_tls ?? true;
    tlsVerify = c.tls_verify ?? true;
    username = c.username ?? '';
    password = '';
    pollInterval = s?.poll_interval ?? 30;
    enabled = s?.enabled ?? true;
    const f = s?.fetch;
    fHost = f?.host ?? '';
    fPort = f?.port ?? 21;
    fUser = f?.username ?? '';
    fPass = '';
    fVerify = f?.tls_verify ?? true;
    fMaps = f ? f.path_mappings.map((m) => ({ ...m })) : [];
    fetchTouched = false;
    error = '';
    testResult = null;
    seenLabels = [];
    if (s) loadSeen(s.id);
  }

  async function loadSeen(id: string) {
    try {
      const page = await endpoints.sourceItems.list({ source_id: id, limit: '500' });
      const set = new Set<string>();
      for (const it of page.items) for (const l of it.labels ?? []) set.add(l);
      seenLabels = [...set].sort();
    } catch {
      /* suggestions are optional */
    }
  }

  const connectionConfig = () => ({
    host,
    port,
    ...(urlPath ? { url_path: urlPath } : {}),
    use_tls: useTls,
    tls_verify: tlsVerify,
    username,
  });

  async function test() {
    testResult = { ok: true, text: 'Testing...' };
    try {
      const r =
        current && !password
          ? await endpoints.sources.test(current.id)
          : await endpoints.sources.testConfig({
              adapter_type: 'rtorrent',
              connection_config: connectionConfig(),
              credential: password,
            });
      testResult = r.ok
        ? { ok: true, text: `Connected${r.version ? ' (v' + r.version + ')' : ''}` }
        : { ok: false, text: r.error ?? r.message ?? 'Connection failed' };
    } catch (e: any) {
      testResult = { ok: false, text: e.message };
    }
  }

  async function scan() {
    if (!current) return;
    error = '';
    try {
      await endpoints.sources.scan(current.id);
      setTimeout(onsaved, 1500); // scan runs in the background; refresh last-scan afterwards
    } catch (e: any) {
      error = e.message;
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = '';
    try {
      const body: Record<string, any> = {
        name,
        connection_config: connectionConfig(),
        poll_interval: pollInterval,
        enabled,
        ...(password ? { credential: password } : {}),
      };
      if ((fetchTouched || !current) && fHost) {
        const fetch: FetchInput = {
          host: fHost,
          port: fPort,
          username: fUser,
          password: fPass,
          tls_verify: fVerify,
          path_mappings: fMaps.filter((m) => m.source_prefix && m.remote_prefix),
        };
        body.fetch = fetch;
      }
      const saved = current
        ? await endpoints.sources.update(current.id, body)
        : await endpoints.sources.create({ ...body, adapter_type: 'rtorrent' });
      load(saved); // keep editor open on the saved source (reveals the tag table after first save)
      onsaved();
    } catch (err: any) {
      error = err.message;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!current) return;
    try {
      await endpoints.sources.delete(current.id);
      confirmOpen = false;
      open = false;
      ondeleted();
    } catch (e: any) {
      confirmOpen = false;
      error = e.message;
    }
  }
</script>

<Modal bind:open title={current ? 'Edit source' : 'Add source'} size="xl">
  <form onsubmit={save} class="flex flex-col gap-6">
    {#if error}<Alert color="red">{error}</Alert>{/if}
    {#if current?.last_scan_error}<Alert color="red">Last scan failed: {current.last_scan_error}</Alert>{/if}

    <section class="grid gap-4 md:grid-cols-2">
      <Heading tag="h3" class="text-lg md:col-span-2">Connection (rTorrent)</Heading>
      <div class="md:col-span-2">
        <Label for="s-name" class="mb-2">Name</Label>
        <Input id="s-name" bind:value={name} required />
      </div>
      <div>
        <Label for="s-host" class="mb-2">Host</Label>
        <Input id="s-host" bind:value={host} required />
      </div>
      <div>
        <Label for="s-port" class="mb-2">Port</Label>
        <Input id="s-port" type="number" bind:value={port} required />
      </div>
      <div class="md:col-span-2">
        <Label for="s-path" class="mb-2">RPC path</Label>
        <Input id="s-path" bind:value={urlPath} placeholder="rutorrent/plugins/rpc/rpc.php" />
      </div>
      <div>
        <Label for="s-user" class="mb-2">Username</Label>
        <Input id="s-user" bind:value={username} autocomplete="off" />
      </div>
      <div>
        <Label for="s-pass" class="mb-2">Password</Label>
        <Input
          id="s-pass"
          type="password"
          autocomplete="new-password"
          bind:value={password}
          placeholder={current?.has_credential ? 'Leave blank to keep the current password' : ''}
        />
      </div>
      <div>
        <Label for="s-poll" class="mb-2">Poll interval (seconds)</Label>
        <Input id="s-poll" type="number" min="5" bind:value={pollInterval} required />
      </div>
      <div class="flex flex-wrap items-end gap-4">
        <Toggle bind:checked={useTls}>TLS</Toggle>
        <Toggle bind:checked={tlsVerify}>Verify certificate</Toggle>
        <Toggle bind:checked={enabled}>Enabled</Toggle>
      </div>
    </section>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <section class="grid gap-4 md:grid-cols-2" oninput={() => (fetchTouched = true)} onchange={() => (fetchTouched = true)}>
      <Heading tag="h3" class="text-lg md:col-span-2">Fetch (FTP, explicit TLS)</Heading>
      <div>
        <Label for="f-host" class="mb-2">Host</Label>
        <Input id="f-host" bind:value={fHost} />
      </div>
      <div>
        <Label for="f-port" class="mb-2">Port</Label>
        <Input id="f-port" type="number" bind:value={fPort} />
      </div>
      <div>
        <Label for="f-user" class="mb-2">Username</Label>
        <Input id="f-user" bind:value={fUser} autocomplete="off" required={!!fHost} />
      </div>
      <div>
        <Label for="f-pass" class="mb-2">Password</Label>
        <Input
          id="f-pass"
          type="password"
          autocomplete="new-password"
          bind:value={fPass}
          required={!!fHost && (fetchTouched || !current)}
          placeholder={current?.fetch?.has_password && !fetchTouched ? '••••• saved' : ''}
        />
      </div>
      <div class="md:col-span-2"><Toggle bind:checked={fVerify}>Verify certificate</Toggle></div>
      <div class="space-y-2 md:col-span-2">
        <Label>Path mappings (rTorrent path to FTP path)</Label>
        {#each fMaps as m, i}
          <div class="flex gap-2">
            <Input placeholder="/downloads/rtorrent" bind:value={m.source_prefix} />
            <Input placeholder="/files" bind:value={m.remote_prefix} />
            <Button
              size="xs"
              color="red"
              onclick={() => {
                fMaps.splice(i, 1);
                fetchTouched = true;
              }}>Remove</Button
            >
          </div>
        {/each}
        <Button
          size="xs"
          color="alternative"
          onclick={() => {
            fMaps.push({ source_prefix: '', remote_prefix: '' });
            fetchTouched = true;
          }}>Add mapping</Button
        >
      </div>
    </section>

    {#if testResult}
      <p class="text-sm {testResult.ok ? 'text-green-500' : 'text-red-500'}">{testResult.text}</p>
    {/if}
    <div class="flex flex-wrap justify-between gap-2">
      <div class="flex gap-2">
        <Button color="alternative" onclick={test}>Test connection</Button>
        {#if current}<Button color="alternative" onclick={scan}>Scan now</Button>{/if}
        {#if current}<Button color="red" outline onclick={() => (confirmOpen = true)}>Delete</Button>{/if}
      </div>
      <div class="flex gap-2">
        <Button color="alternative" onclick={() => (open = false)}>Close</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving...' : 'Save'}</Button>
      </div>
    </div>
  </form>

  <div class="mt-6 space-y-3">
    <Heading tag="h3" class="text-lg">Tag mappings</Heading>
    {#if current}
      {#key current.id}
        <TagRulesTable sourceId={current.id} {libraries} {seenLabels} />
      {/key}
    {:else}
      <p class="text-sm text-gray-500 dark:text-gray-400">Save the source first to map tags to libraries.</p>
    {/if}
  </div>
</Modal>

<Modal bind:open={confirmOpen} title="Delete source" size="xs">
  <p>Delete <strong>{current?.name}</strong>? Its tag mappings and FTP fetch config are removed too.</p>
  <div class="mt-4 flex justify-end gap-2">
    <Button color="alternative" onclick={() => (confirmOpen = false)}>Cancel</Button>
    <Button color="red" onclick={remove}>Delete</Button>
  </div>
</Modal>

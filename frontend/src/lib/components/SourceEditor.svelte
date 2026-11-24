<script lang="ts">
  import { untrack } from 'svelte';
  import { Modal, Button, Input, Label, Toggle, Alert, Spinner } from 'flowbite-svelte';
  import { endpoints, type Source, type Library, type FetchInput, type LabelRule } from '$lib/api/client';
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
  let connTouched = $state(false);
  // Renaming alone must not count as a connection edit
  const touch = (e: Event) => {
    if ((e.target as HTMLElement).id !== 's-name') connTouched = true;
  };

  let error = $state('');
  type TestResult = { ok: boolean; text: string };
  let testResult = $state<TestResult | null>(null); // rTorrent
  let fetchResult = $state<TestResult | null>(null); // FTP
  let busy = $state(false);
  let confirmOpen = $state(false);
  let seenLabels = $state<string[]>([]);
  let tab = $state<'conn' | 'tags' | 'fetch'>('conn');
  // Tag edits are a draft; Save diffs them against savedTags and writes the changes.
  let tags = $state<LabelRule[]>([]);
  let savedTags = $state<LabelRule[]>([]);
  let testing = $state(false);
  let fetchTesting = $state(false);

  // Required fields per tab; a tab with gaps shows a red dot and blocks save.
  const connMissing = $derived(!name.trim() || !host.trim());
  const fetchUsed = $derived(!!(fHost || fUser || fPass));
  // Empty password keeps the saved one (backend), so only require it when none is saved.
  const pwSaved = $derived(!!current?.fetch?.has_password);
  const fetchMissing = $derived(
    fetchUsed && (!fHost.trim() || !fUser.trim() || (!fPass && !pwSaved)),
  );

  // Reset the form each time the editor opens.
  $effect(() => {
    if (!open) return;
    // untrack: load() reads and writes state; tracking it would re-run this effect forever.
    untrack(() => {
      tab = 'conn';
      load(source);
    });
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
    connTouched = false;
    error = '';
    testResult = null;
    fetchResult = null;
    seenLabels = [];
    tags = [];
    savedTags = [];
    if (s) {
      loadSeen(s.id);
      loadTags(s.id);
    }
  }

  async function loadTags(id: string) {
    try {
      const list = await endpoints.sources.labels.list(id);
      if (current?.id !== id) return;
      savedTags = list;
      tags = list.map((t) => ({ ...t }));
    } catch (e: any) {
      error = e.message;
    }
  }

  const tagFields = (t: LabelRule) => ({
    label: t.label,
    library_instance_id: t.library_instance_id,
    temporary_directory: t.temporary_directory,
    completed_directory: t.completed_directory,
    enabled: t.enabled,
    automatic_processing: t.automatic_processing,
  });

  // Writes tag changes; savedTags tracks progress so a retry after a failure redoes only what's left.
  async function syncTags(sourceId: string) {
    const keep = new Set(tags.map((t) => t.id));
    for (const old of savedTags.filter((t) => !keep.has(t.id))) {
      await endpoints.sources.labels.delete(sourceId, old.id);
      savedTags = savedTags.filter((t) => t.id !== old.id);
    }
    for (const t of tags) {
      const old = savedTags.find((o) => o.id === t.id);
      if (!old) {
        const created = await endpoints.sources.labels.create(sourceId, tagFields(t));
        tags = tags.map((x) => (x.id === t.id ? created : x));
        savedTags = [...savedTags, created];
      } else if (JSON.stringify(tagFields(old)) !== JSON.stringify(tagFields(t))) {
        const updated = await endpoints.sources.labels.update(sourceId, t.id, tagFields(t));
        savedTags = savedTags.map((x) => (x.id === t.id ? updated : x));
      }
    }
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
    if (current && connTouched && !password) {
      testResult = { ok: false, text: 'Enter the password to test changed settings' };
      return;
    }
    testResult = null;
    testing = true;
    try {
      const r =
        current && !connTouched
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
    } finally {
      testing = false;
    }
  }

  // Tests the FTP fields as typed; a blank password falls back to the saved one.
  async function testFetch() {
    if (!fHost.trim() || !fUser.trim()) {
      fetchResult = { ok: false, text: 'Enter host and username first' };
      return;
    }
    fetchResult = null;
    fetchTesting = true;
    try {
      const r = await endpoints.sources.fetchTest({
        host: fHost,
        port: fPort,
        username: fUser,
        password: fPass,
        tls_verify: fVerify,
        path_mappings: [],
        ...(current ? { source_id: current.id } : {}),
      });
      fetchResult = r.ok ? { ok: true, text: 'Connected' } : { ok: false, text: r.error ?? 'Connection failed' };
    } catch (e: any) {
      fetchResult = { ok: false, text: e.message };
    } finally {
      fetchTesting = false;
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (connMissing || fetchMissing) {
      tab = connMissing ? 'conn' : 'fetch';
      error = 'Fill in the required fields marked *';
      return;
    }
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
      if (current) await endpoints.sources.update(current.id, body);
      // Remember a new source so a retry after a failed tag updates it instead of duplicating it.
      else current = await endpoints.sources.create({ ...body, adapter_type: 'rtorrent' });
      await syncTags(current.id);
      open = false;
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

{#snippet tester(run: () => void, busy: boolean, result: TestResult | null)}
  <div class="flex flex-wrap items-center gap-3 md:col-span-2">
    <Button size="sm" color="alternative" disabled={busy} onclick={run}>
      {#if busy}<Spinner size="4" class="me-2" />{/if}Test connection
    </Button>
    {#if result}
      <span class="text-sm {result.ok ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-300'}"
        >{result.text}</span
      >
    {/if}
  </div>
{/snippet}

{#snippet tabButton(id: 'conn' | 'tags' | 'fetch', label: string, missing: boolean)}
  <button
    type="button"
    role="tab"
    aria-selected={tab === id}
    class="-mb-px flex items-center border-b-2 px-4 py-2 text-sm font-medium {tab === id
      ? 'border-primary-500 text-primary-500'
      : 'border-transparent text-gray-500 hover:text-gray-300 dark:text-gray-400'}"
    onclick={() => (tab = id)}
  >
    {label}
    {#if missing}<span class="ms-1.5 inline-block h-2 w-2 rounded-full bg-red-500" title="Required fields missing"></span>{/if}
  </button>
{/snippet}

<Modal bind:open title={current ? `Edit source: ${current.name}` : 'Add source'} size="lg">
  <div class="flex flex-col gap-4">
    {#if error}<Alert color="red">{error}</Alert>{/if}
    {#if current?.last_scan_error}<Alert color="red">Last scan failed: {current.last_scan_error}</Alert>{/if}

    <div role="tablist" class="flex border-b border-gray-200 dark:border-gray-700">
      {@render tabButton('conn', 'Connection', connMissing)}
      {@render tabButton('tags', `Tags (${tags.length})`, false)}
      {@render tabButton('fetch', 'Fetch (FTP)', fetchMissing)}
    </div>

    <form id="source-form" onsubmit={save} novalidate>
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <section class="grid gap-4 md:grid-cols-2" class:hidden={tab !== 'conn'} oninput={touch} onchange={touch}>
        <div class="md:col-span-2">
          <Label for="s-name" class="mb-2">Name *</Label>
          <Input id="s-name" bind:value={name} placeholder="Seedbox" />
        </div>
        <div class="md:col-span-2">
          <Label for="s-host" class="mb-2">rTorrent host *</Label>
          <Input id="s-host" bind:value={host} placeholder="box.example.com" />
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
            placeholder={current?.has_credential ? '••••• saved' : ''}
          />
        </div>
        <div class="md:col-span-2"><Toggle bind:checked={enabled}>Enabled</Toggle></div>
        <details class="rounded-lg border border-gray-200 p-3 md:col-span-2 dark:border-gray-700">
          <summary class="cursor-pointer text-sm font-medium text-gray-500 dark:text-gray-400">Advanced</summary>
          <div class="mt-3 grid gap-4 md:grid-cols-2">
            <div>
              <Label for="s-port" class="mb-2">Port</Label>
              <Input id="s-port" type="number" bind:value={port} />
            </div>
            <div>
              <Label for="s-poll" class="mb-2">Poll interval (seconds)</Label>
              <Input id="s-poll" type="number" min="5" bind:value={pollInterval} />
            </div>
            <div class="md:col-span-2">
              <Label for="s-path" class="mb-2">RPC path</Label>
              <Input id="s-path" bind:value={urlPath} placeholder="rutorrent/plugins/rpc/rpc.php" />
            </div>
            <div class="flex flex-wrap gap-4 md:col-span-2">
              <Toggle bind:checked={useTls}>TLS</Toggle>
              <Toggle bind:checked={tlsVerify}>Verify certificate</Toggle>
            </div>
          </div>
        </details>
        {@render tester(test, testing, testResult)}
      </section>

      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <section
        class="grid gap-4 md:grid-cols-2"
        class:hidden={tab !== 'fetch'}
        oninput={() => (fetchTouched = true)}
        onchange={() => (fetchTouched = true)}
      >
        <p class="text-sm text-gray-500 md:col-span-2 dark:text-gray-400">
          How finished downloads are fetched (FTP, explicit TLS). Optional: without it, jobs wait on the seedbox.
        </p>
        <div class="md:col-span-2">
          <Label for="f-host" class="mb-2">FTP host{fetchUsed ? ' *' : ''}</Label>
          <Input id="f-host" bind:value={fHost} placeholder="ftp.example.com" />
        </div>
        <div>
          <Label for="f-user" class="mb-2">Username{fetchUsed ? ' *' : ''}</Label>
          <Input id="f-user" bind:value={fUser} autocomplete="off" />
        </div>
        <div>
          <Label for="f-pass" class="mb-2">Password{fetchUsed && !pwSaved ? ' *' : ''}</Label>
          <Input
            id="f-pass"
            type="password"
            autocomplete="new-password"
            bind:value={fPass}
            placeholder={pwSaved ? '••••• saved' : ''}
          />
        </div>
        <div class="space-y-2 md:col-span-2">
          <Label>Path mappings (rTorrent path → FTP path)</Label>
          {#each fMaps as m, i}
            <div class="flex gap-2">
              <Input placeholder="/downloads/rtorrent" bind:value={m.source_prefix} />
              <Input placeholder="/files" bind:value={m.remote_prefix} />
              <Button
                size="xs"
                color="alternative"
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
        <details class="rounded-lg border border-gray-200 p-3 md:col-span-2 dark:border-gray-700">
          <summary class="cursor-pointer text-sm font-medium text-gray-500 dark:text-gray-400">Advanced</summary>
          <div class="mt-3 grid gap-4 md:grid-cols-2">
            <div>
              <Label for="f-port" class="mb-2">Port</Label>
              <Input id="f-port" type="number" bind:value={fPort} />
            </div>
            <div class="flex items-end"><Toggle bind:checked={fVerify}>Verify certificate</Toggle></div>
          </div>
        </details>
        {@render tester(testFetch, fetchTesting, fetchResult)}
      </section>
    </form>

    <div class:hidden={tab !== 'tags'}>
      {#key current?.id}
        <TagRulesTable bind:rules={tags} {libraries} {seenLabels} />
      {/key}
    </div>

    <div class="flex flex-wrap items-center gap-2 border-t border-gray-200 pt-4 dark:border-gray-700">
      {#if current}<Button color="red" outline onclick={() => (confirmOpen = true)}>Delete</Button>{/if}
      <Button color="alternative" class="ms-auto" onclick={() => (open = false)}>Close</Button>
      <Button type="submit" form="source-form" disabled={busy}>
        {#if busy}<Spinner size="4" class="me-2" />{/if}Save
      </Button>
    </div>
  </div>
</Modal>

<Modal bind:open={confirmOpen} title="Delete source" size="xs">
  <p>Delete <strong>{current?.name}</strong>? Its tag mappings and FTP fetch config are removed too.</p>
  <div class="mt-4 flex justify-end gap-2">
    <Button color="alternative" onclick={() => (confirmOpen = false)}>Cancel</Button>
    <Button color="red" onclick={remove}>Delete</Button>
  </div>
</Modal>

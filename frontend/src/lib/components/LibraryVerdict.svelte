<script lang="ts">
  /** What the library check decided, and what it parsed and matched to get there. */
  let { progress: p }: { progress: any } = $props();

  const parsed = $derived(p.match?.parsed ?? {});
</script>

<dl class="mt-1 ms-6 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
  {#if p.eligibility === 'skipped_by_user'}
    <dt class="text-gray-500 dark:text-gray-400">Verdict</dt><dd class="text-gray-800 dark:text-gray-100">Skipped by you</dd>
  {:else}
    {#if p.library}<dt class="text-gray-500 dark:text-gray-400">Library</dt><dd class="text-gray-800 dark:text-gray-100">{p.library}</dd>{/if}
    <dt class="text-gray-500 dark:text-gray-400">Verdict</dt>
    <dd class="text-gray-800 dark:text-gray-100">{p.eligibility.replaceAll('_', ' ')}{#if p.reason}<span class="text-gray-500 dark:text-gray-400">{` · ${p.reason}`}</span>{/if}</dd>
    {#if p.match}
      <dt class="text-gray-500 dark:text-gray-400">Parsed as</dt>
      <dd class="text-gray-800 dark:text-gray-100">
        {parsed.title ?? '—'}{#if parsed.year}{` (${parsed.year})`}{/if}{#if parsed.season != null}{` · S${String(parsed.season).padStart(2, '0')}`}{/if}{#if parsed.episodes}{` E${parsed.episodes.join(', E')}`}{:else if parsed.full_season}{' · full season'}{/if}{#if parsed.edition}{` · ${parsed.edition}`}{/if}
      </dd>
      {#if parsed.quality || parsed.group}
        <dt class="text-gray-500 dark:text-gray-400">Release</dt>
        <dd class="text-gray-800 dark:text-gray-100">{[parsed.quality, parsed.group].filter(Boolean).join(' · ')}</dd>
      {/if}
      <dt class="text-gray-500 dark:text-gray-400">Matched</dt>
      <dd class="text-gray-800 dark:text-gray-100">
        {p.match.catalog_id != null ? `${p.match.media_type} #${p.match.catalog_id}` : 'no library entry'}{#if p.match.episode_ids}{` · ${p.match.episode_ids} episodes`}{/if}
      </dd>
    {/if}
    {#if p.evidence?.has_file != null}
      <dt class="text-gray-500 dark:text-gray-400">In library</dt>
      <dd class="text-gray-800 dark:text-gray-100">{p.evidence.has_file ? 'has a file' : 'no file'}{#if p.evidence.missing_episode_ids?.length}{` · ${p.evidence.missing_episode_ids.length} episodes missing`}{/if}</dd>
    {/if}
  {/if}
</dl>

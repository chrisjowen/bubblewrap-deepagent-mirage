<script lang="ts">
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import FileTree from '$lib/components/FileTree.svelte';
	import ChatPane from '$lib/components/ChatPane.svelte';

	const id = $derived(page.params.id ?? '');

	let runtime = $state<string | null>(null);
	let selectedPath = $state<string | null>(null);
	let preview = $state<string | null>(null);
	let openError = $state<string | null>(null);
	let previewError = $state<string | null>(null);

	$effect(() => {
		if (!id) return;
		openError = null;
		api
			.openWorkspace(id)
			.then((r) => (runtime = r.runtime))
			.catch((e) => (openError = String(e)));
	});

	$effect(() => {
		if (!id || !selectedPath) return;
		previewError = null;
		api
			.readFile(id, selectedPath)
			.then((t) => (preview = t as string))
			.catch((e) => (previewError = String(e)));
	});
</script>

<div class="mb-4 flex items-center gap-2">
	<h1 class="text-lg font-medium">{id}</h1>
	{#if runtime}
		<span class="rounded bg-neutral-800 px-2 py-0.5 text-xs font-mono">{runtime}</span>
	{/if}
	{#if openError}
		<span class="text-xs text-red-400 font-mono">{openError}</span>
	{/if}
</div>

<div class="grid gap-4 grid-cols-12">
	<aside class="col-span-3 rounded border border-neutral-800 p-3">
		<FileTree workspaceId={id} onSelect={(p) => (selectedPath = p)} />
	</aside>

	<section class="col-span-5 rounded border border-neutral-800 p-3">
		{#if previewError}
			<div class="text-xs font-mono text-red-400">{previewError}</div>
		{:else if selectedPath && preview !== null}
			<div class="mb-2 text-xs font-mono opacity-60">{selectedPath}</div>
			<pre class="whitespace-pre-wrap font-mono text-xs">{preview}</pre>
		{:else}
			<div class="text-sm opacity-50">Select a file</div>
		{/if}
	</section>

	<section class="col-span-4 rounded border border-neutral-800 p-3 flex flex-col" style="height: calc(100vh - 12rem)">
		{#if runtime}
			<ChatPane workspaceId={id} />
		{:else}
			<div class="text-xs opacity-50">Waiting for workspace…</div>
		{/if}
	</section>
</div>

<script lang="ts">
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import FileTree from '$lib/components/FileTree.svelte';
	import ChatPane from '$lib/components/ChatPane.svelte';
	import Viewer from '$lib/components/Viewer.svelte';

	const id = $derived(page.params.id ?? '');

	let label = $state<string | null>(null);
	let runtime = $state<string | null>(null);
	let mountName = $state<string | null>(null);
	let selectedPath = $state<string | null>(null);
	let openError = $state<string | null>(null);
	let treeRefreshTick = $state(0);

	$effect(() => {
		if (!id) return;
		openError = null;
		label = null;
		runtime = null;
		mountName = null;
		selectedPath = null;
		api
			.openWorkspace(id)
			.then((r) => {
				label = r.label;
				runtime = r.runtime;
				mountName = r.mount_name;
			})
			.catch((e) => (openError = String(e)));
	});

	function handleRemoved(path: string) {
		if (selectedPath === path) selectedPath = null;
	}
	function handleRenamed(oldPath: string, newPath: string) {
		if (selectedPath === oldPath) selectedPath = newPath;
	}

	function runtimeColor(rt: string) {
		if (rt === 'docker-local') return 'bg-sky-900 text-sky-200';
		if (rt === 'code-interpreter') return 'bg-amber-900 text-amber-200';
		return 'bg-neutral-800';
	}
</script>

<div class="mb-4 flex items-center gap-3">
	<a href="/" class="text-neutral-500 hover:text-neutral-200 text-sm">← workspaces</a>
	<h1 class="text-lg font-medium">{label ?? id}</h1>
	<span class="text-[11px] font-mono opacity-40">{id}</span>
	{#if runtime}
		<span class="rounded px-2 py-0.5 text-xs font-mono {runtimeColor(runtime)}">{runtime}</span>
	{/if}
	{#if mountName}
		<span class="rounded bg-neutral-800 px-2 py-0.5 text-xs font-mono opacity-70">/{mountName}</span>
	{/if}
	{#if openError}
		<span class="text-xs text-red-400 font-mono">{openError}</span>
	{/if}
</div>

<div class="grid gap-4 grid-cols-12" style="height: calc(100vh - 8rem)">
	<aside class="col-span-3 rounded border border-neutral-800 p-3 overflow-hidden">
		<FileTree
			workspaceId={id}
			{selectedPath}
			externalRefreshTick={treeRefreshTick}
			onSelect={(p) => (selectedPath = p)}
			onPathRemoved={handleRemoved}
			onPathRenamed={handleRenamed}
		/>
	</aside>

	<section class="col-span-6 rounded border border-neutral-800 p-3 flex flex-col overflow-hidden">
		{#if runtime}
			<ChatPane
				workspaceId={id}
				{runtime}
				mountName={mountName ?? ''}
				onAgentMutation={() => (treeRefreshTick += 1)}
			/>
		{:else}
			<div class="text-xs opacity-50">Waiting for workspace…</div>
		{/if}
	</section>

	<section class="col-span-3 rounded border border-neutral-800 p-3 overflow-hidden">
		{#if selectedPath}
			{#key selectedPath}
				<Viewer workspaceId={id} path={selectedPath} />
			{/key}
		{:else}
			<div class="text-sm opacity-50">Select a file</div>
		{/if}
	</section>
</div>

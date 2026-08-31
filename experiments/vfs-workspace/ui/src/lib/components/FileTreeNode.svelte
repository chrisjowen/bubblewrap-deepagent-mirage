<script lang="ts">
	import { api, type TreeEntry } from '$lib/api';
	import Self from './FileTreeNode.svelte';

	let {
		workspaceId,
		entry,
		depth,
		selectedPath,
		version,
		onSelect,
		onContext
	}: {
		workspaceId: string;
		entry: TreeEntry;
		depth: number;
		selectedPath?: string | null;
		version: number;
		onSelect: (path: string) => void;
		onContext: (e: MouseEvent, entry: TreeEntry) => void;
	} = $props();

	let expanded = $state(false);
	let loading = $state(false);
	let children = $state<TreeEntry[] | null>(null);
	let error = $state<string | null>(null);
	let lastVersion = -1;

	const displayName = $derived(entry.path.replace(/\/$/, '').split('/').pop() || '/');
	const pad = $derived(depth * 12);
	const selected = $derived(!entry.is_dir && selectedPath === entry.path);

	async function loadChildren() {
		if (!entry.is_dir) return;
		loading = true;
		error = null;
		try {
			const t = await api.tree(workspaceId, entry.path);
			children = t.entries;
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (expanded && version !== lastVersion) {
			lastVersion = version;
			loadChildren();
		}
	});

	async function toggle() {
		if (!entry.is_dir) return;
		expanded = !expanded;
		if (expanded && children === null && !loading) {
			lastVersion = version;
			await loadChildren();
		}
	}

	function context(e: MouseEvent) {
		onContext(e, entry);
	}
</script>

<li>
	<div
		class="flex items-center gap-1 rounded"
		class:bg-neutral-800={selected}
		style="padding-left: {pad}px"
		oncontextmenu={context}
		role="treeitem"
		aria-selected={selected}
		tabindex="-1"
	>
		{#if entry.is_dir}
			<button
				onclick={toggle}
				class="w-3 text-left opacity-60 hover:opacity-100"
				aria-label={expanded ? 'collapse' : 'expand'}
			>
				{expanded ? '▾' : '▸'}
			</button>
			<button onclick={toggle} class="text-left hover:text-blue-400 transition flex-1">
				📁 {displayName}
			</button>
		{:else}
			<span class="w-3"></span>
			<button
				onclick={() => onSelect(entry.path)}
				class="text-left hover:text-blue-400 transition flex-1"
				class:text-blue-300={selected}
			>
				📄 {displayName}
			</button>
		{/if}
	</div>
	{#if expanded}
		{#if loading}
			<div class="opacity-50 text-[10px]" style="padding-left: {pad + 24}px">…</div>
		{:else if error}
			<div class="text-red-400 text-[10px]" style="padding-left: {pad + 24}px">{error}</div>
		{:else if children}
			<ul class="space-y-0.5">
				{#each children as c (c.path)}
					<Self
						{workspaceId}
						entry={c}
						depth={depth + 1}
						{selectedPath}
						{version}
						{onSelect}
						{onContext}
					/>
				{/each}
			</ul>
		{/if}
	{/if}
</li>

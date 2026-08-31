<script lang="ts">
	import { api, type TreeEntry } from '$lib/api';
	import FileTreeNode from './FileTreeNode.svelte';
	import ContextMenu, { type MenuItem } from './ContextMenu.svelte';

	let {
		workspaceId,
		selectedPath = null,
		externalRefreshTick = 0,
		onSelect,
		onPathRemoved,
		onPathRenamed
	}: {
		workspaceId: string;
		selectedPath?: string | null;
		externalRefreshTick?: number;
		onSelect: (path: string) => void;
		onPathRemoved?: (path: string) => void;
		onPathRenamed?: (oldPath: string, newPath: string) => void;
	} = $props();

	let entries = $state<TreeEntry[]>([]);
	let error = $state<string | null>(null);
	let version = $state(0);
	let pendingForce = false;
	let lastExternalTick = 0;

	async function loadRoot(force = false) {
		try {
			const t = await api.tree(workspaceId, '/', force);
			entries = t.entries;
			error = null;
		} catch (e) {
			error = String(e);
		}
	}

	$effect(() => {
		void workspaceId;
		void version;
		const force = pendingForce;
		pendingForce = false;
		loadRoot(force);
	});

	$effect(() => {
		if (externalRefreshTick !== lastExternalTick) {
			lastExternalTick = externalRefreshTick;
			forceRefresh();
		}
	});

	function bumpVersion() {
		version += 1;
	}

	function forceRefresh() {
		pendingForce = true;
		version += 1;
	}

	function joinRoot(name: string): string {
		const n = name.replace(/^\/+/, '');
		return `/${n}`;
	}

	async function newFileAt(dirPath: string) {
		const name = prompt(`New file in ${dirPath} (name or relative path):`);
		if (!name) return;
		const full = dirPath === '/' ? joinRoot(name) : `${dirPath.replace(/\/$/, '')}/${name}`;
		try {
			await api.writeFile(workspaceId, full, '');
			bumpVersion();
			onSelect(full);
		} catch (e) {
			alert(`Create failed: ${e}`);
		}
	}

	async function newFolderAt(dirPath: string) {
		const name = prompt(`New folder in ${dirPath}:`);
		if (!name) return;
		const full = dirPath === '/' ? joinRoot(name) : `${dirPath.replace(/\/$/, '')}/${name}`;
		try {
			await api.mkdir(workspaceId, full);
			bumpVersion();
		} catch (e) {
			alert(`mkdir failed: ${e}`);
		}
	}

	async function renamePath(oldPath: string) {
		const next = prompt('New path (absolute; use / to move):', oldPath);
		if (!next || next === oldPath) return;
		try {
			await api.move(workspaceId, oldPath, next);
			bumpVersion();
			onPathRenamed?.(oldPath, next);
		} catch (e) {
			alert(`Move failed: ${e}`);
		}
	}

	async function deletePath(p: string) {
		if (!confirm(`Delete ${p}?`)) return;
		try {
			await api.deleteFile(workspaceId, p);
			bumpVersion();
			onPathRemoved?.(p);
		} catch (e) {
			alert(`Delete failed: ${e}`);
		}
	}

	let menuOpen = $state(false);
	let menuX = $state(0);
	let menuY = $state(0);
	let menuItems = $state<MenuItem[]>([]);

	function closeMenu() {
		menuOpen = false;
	}

	function openMenuFor(e: MouseEvent, entry: TreeEntry) {
		e.preventDefault();
		e.stopPropagation();
		menuX = e.clientX;
		menuY = e.clientY;
		const p = entry.path;
		if (entry.is_dir) {
			menuItems = [
				{ label: 'New file…', onClick: () => newFileAt(p) },
				{ label: 'New folder…', onClick: () => newFolderAt(p) },
				{ label: 'Rename / Move…', onClick: () => renamePath(p) },
				{ label: 'Delete', danger: true, onClick: () => deletePath(p) }
			];
		} else {
			menuItems = [
				{ label: 'Rename / Move…', onClick: () => renamePath(p) },
				{ label: 'Delete', danger: true, onClick: () => deletePath(p) }
			];
		}
		menuOpen = true;
	}

	function openRootMenu(e: MouseEvent) {
		e.preventDefault();
		menuX = e.clientX;
		menuY = e.clientY;
		menuItems = [
			{ label: 'New file…', onClick: () => newFileAt('/') },
			{ label: 'New folder…', onClick: () => newFolderAt('/') }
		];
		menuOpen = true;
	}
</script>

<div class="flex flex-col gap-2 h-full" oncontextmenu={openRootMenu} role="tree" tabindex="-1">
	<div class="flex items-center justify-between text-xs">
		<span class="font-mono opacity-60">files</span>
		<div class="flex gap-1">
			<button
				type="button"
				title="New file"
				class="rounded border border-neutral-700 px-1.5 py-0.5 hover:bg-neutral-800"
				onclick={() => newFileAt('/')}
			>
				+ file
			</button>
			<button
				type="button"
				title="New folder"
				class="rounded border border-neutral-700 px-1.5 py-0.5 hover:bg-neutral-800"
				onclick={() => newFolderAt('/')}
			>
				+ dir
			</button>
			<button
				type="button"
				title="Force refresh (drops server cache)"
				class="rounded border border-neutral-700 px-1.5 py-0.5 hover:bg-neutral-800"
				onclick={forceRefresh}
				aria-label="refresh"
			>
				↻
			</button>
		</div>
	</div>

	{#if error}
		<div class="text-red-400 text-xs font-mono">{error}</div>
	{:else}
		<ul class="space-y-0.5 font-mono text-xs flex-1 overflow-auto">
			{#each entries as e (e.path)}
				<FileTreeNode
					{workspaceId}
					entry={e}
					depth={0}
					{selectedPath}
					{version}
					{onSelect}
					onContext={(ev, en) => openMenuFor(ev, en)}
				/>
			{/each}
		</ul>
	{/if}
</div>

<ContextMenu open={menuOpen} x={menuX} y={menuY} items={menuItems} onClose={closeMenu} />

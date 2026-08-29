<script lang="ts">
	import { api, type TreeEntry } from '$lib/api';
	import FileTreeNode from './FileTreeNode.svelte';

	let { workspaceId, onSelect }: { workspaceId: string; onSelect: (path: string) => void } =
		$props();

	let entries = $state<TreeEntry[]>([]);
	let error = $state<string | null>(null);

	$effect(() => {
		api
			.tree(workspaceId, '/')
			.then((t) => (entries = t.entries))
			.catch((e) => (error = String(e)));
	});
</script>

{#if error}
	<div class="text-red-400 text-xs font-mono">{error}</div>
{:else}
	<ul class="space-y-0.5 font-mono text-xs">
		{#each entries as e}
			<FileTreeNode {workspaceId} entry={e} depth={0} {onSelect} />
		{/each}
	</ul>
{/if}

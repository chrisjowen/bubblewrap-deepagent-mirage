<script lang="ts">
	import { api, type TreeEntry } from '$lib/api';

	let { workspaceId, onSelect }: { workspaceId: string; onSelect: (path: string) => void } =
		$props();

	let entries = $state<TreeEntry[]>([]);
	let error = $state<string | null>(null);

	$effect(() => {
		api
			.tree(workspaceId)
			.then((t) => (entries = t.entries))
			.catch((e) => (error = String(e)));
	});
</script>

{#if error}
	<div class="text-red-400 text-xs font-mono">{error}</div>
{:else}
	<ul class="space-y-1 font-mono text-xs">
		{#each entries as e}
			<li>
				{#if e.is_dir}
					<span class="opacity-60">📁 {e.path}</span>
				{:else}
					<button
						class="text-left hover:text-blue-400 transition"
						onclick={() => onSelect(e.path)}
					>
						📄 {e.path}
					</button>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

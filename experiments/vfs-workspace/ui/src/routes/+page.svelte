<script lang="ts">
	import { api, type Workspace } from '$lib/api';

	let workspaces = $state<Workspace[]>([]);
	let error = $state<string | null>(null);
	let loading = $state(true);

	$effect(() => {
		api
			.listWorkspaces()
			.then((w) => {
				workspaces = w;
				loading = false;
			})
			.catch((e) => {
				error = String(e);
				loading = false;
			});
	});
</script>

<h1 class="mb-4 text-lg font-medium">Workspaces</h1>

{#if loading}
	<div class="text-neutral-400 text-sm">loading…</div>
{:else if error}
	<div class="text-red-400 text-sm font-mono">{error}</div>
{:else if workspaces.length === 0}
	<div class="text-neutral-400 text-sm">no workspaces configured</div>
{:else}
	<div class="grid gap-3 grid-cols-1 md:grid-cols-3">
		{#each workspaces as ws}
			<a
				href={`/w/${ws.id}`}
				class="block rounded border border-neutral-800 p-4 hover:border-neutral-600 transition"
			>
				<div class="text-base font-medium">{ws.id}</div>
				<div class="mt-2 inline-block rounded bg-neutral-800 px-2 py-0.5 text-xs">
					{ws.runtime}
				</div>
			</a>
		{/each}
	</div>
{/if}

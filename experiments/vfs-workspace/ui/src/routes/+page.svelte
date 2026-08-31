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

	function runtimeColor(rt: string) {
		if (rt === 'docker-local') return 'bg-sky-900 text-sky-200';
		if (rt === 'code-interpreter') return 'bg-amber-900 text-amber-200';
		return 'bg-neutral-800 text-neutral-300';
	}
</script>

<h1 class="mb-4 text-lg font-medium">Workspaces</h1>

{#if loading}
	<div class="text-neutral-400 text-sm">loading…</div>
{:else if error}
	<div class="text-red-400 text-sm font-mono">{error}</div>
{:else if workspaces.length === 0}
	<div class="text-neutral-400 text-sm">no workspaces configured</div>
{:else}
	<div class="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
		{#each workspaces as ws}
			<a
				href={`/w/${ws.id}`}
				class="block rounded border border-neutral-800 p-4 hover:border-neutral-500 transition"
			>
				<div class="text-base font-medium">{ws.label ?? ws.id}</div>
				<div class="mt-1 text-[11px] font-mono opacity-50">{ws.id}</div>
				<div class="mt-3 flex flex-wrap gap-1.5">
					<span class="inline-block rounded px-2 py-0.5 text-[10px] font-mono {runtimeColor(ws.runtime)}">
						{ws.runtime}
					</span>
					{#if ws.mount_name}
						<span class="inline-block rounded bg-neutral-800 px-2 py-0.5 text-[10px] font-mono opacity-70">
							/{ws.mount_name}
						</span>
					{/if}
				</div>
			</a>
		{/each}
	</div>
{/if}

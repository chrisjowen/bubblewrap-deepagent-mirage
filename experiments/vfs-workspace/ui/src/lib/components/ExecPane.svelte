<script lang="ts">
	import { api, type ExecResp } from '$lib/api';

	let { workspaceId, runtime }: { workspaceId: string; runtime: string } = $props();

	let language = $state<'python' | 'node'>('python');
	let code = $state("print('hello from vfs-workspace')");
	let result = $state<ExecResp | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);

	const nodeDisabled = $derived(runtime === 'code-interpreter');

	async function run() {
		busy = true;
		error = null;
		result = null;
		try {
			result = await api.exec(workspaceId, { language, code });
		} catch (e) {
			error = String(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="space-y-3">
	<div class="flex items-center gap-2">
		<select
			bind:value={language}
			class="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs"
		>
			<option value="python">Python</option>
			<option value="node" disabled={nodeDisabled}>Node{nodeDisabled ? ' (N/A)' : ''}</option>
		</select>
		<button
			onclick={run}
			disabled={busy}
			class="rounded bg-blue-600 px-3 py-1 text-xs font-medium hover:bg-blue-500 disabled:opacity-50"
		>
			{busy ? 'Running…' : 'Run'}
		</button>
	</div>

	<textarea
		bind:value={code}
		rows="12"
		class="w-full rounded border border-neutral-700 bg-neutral-900 p-2 font-mono text-xs"
	></textarea>

	{#if error}
		<div class="rounded border border-red-900 bg-red-950 p-2 text-xs font-mono text-red-300">
			{error}
		</div>
	{/if}

	{#if result}
		<div class="rounded border border-neutral-800 p-2 text-xs font-mono">
			<div class="opacity-60">exit={result.exit_code} · {result.elapsed_ms}ms</div>
			{#if result.stdout}
				<pre class="mt-2 whitespace-pre-wrap">{result.stdout}</pre>
			{/if}
			{#if result.stderr}
				<pre class="mt-2 whitespace-pre-wrap text-red-400">{result.stderr}</pre>
			{/if}
		</div>
	{/if}
</div>

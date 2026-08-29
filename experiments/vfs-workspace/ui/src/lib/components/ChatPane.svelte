<script lang="ts">
	interface ChatMsg {
		role: 'user' | 'assistant';
		text: string;
		tools?: { name: string; input: unknown; result?: string; is_error?: boolean }[];
	}

	let { workspaceId }: { workspaceId: string } = $props();

	let messages = $state<ChatMsg[]>([]);
	let input = $state('');
	let busy = $state(false);
	let error = $state<string | null>(null);

	async function send() {
		if (!input.trim() || busy) return;
		error = null;
		busy = true;
		const userMsg: ChatMsg = { role: 'user', text: input.trim() };
		messages = [...messages, userMsg];
		input = '';

		const assistantMsg: ChatMsg = { role: 'assistant', text: '', tools: [] };
		messages = [...messages, assistantMsg];

		try {
			const wire = messages.slice(0, -1).map((m) => ({ role: m.role, content: m.text }));
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ workspaceId, messages: wire })
			});
			if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				const events = buffer.split('\n\n');
				buffer = events.pop() ?? '';
				for (const raw of events) {
					const line = raw.trim();
					if (!line.startsWith('data:')) continue;
					const payload = JSON.parse(line.slice(5).trim());
					const last = messages[messages.length - 1];
					if (payload.type === 'text') {
						last.text += payload.text;
					} else if (payload.type === 'tool_use') {
						last.tools = [...(last.tools ?? []), { name: payload.name, input: payload.input }];
					} else if (payload.type === 'tool_result') {
						const t = last.tools?.[last.tools.length - 1];
						if (t) {
							t.result = payload.text;
							t.is_error = payload.is_error;
						}
					} else if (payload.type === 'error') {
						error = payload.message;
					}
					messages = [...messages];
				}
			}
		} catch (e) {
			error = String(e);
		} finally {
			busy = false;
		}
	}

	function keydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			send();
		}
	}
</script>

<div class="flex flex-col h-full min-h-0">
	<div class="flex-1 overflow-y-auto space-y-3 pr-1 min-h-0">
		{#each messages as m}
			<div class="text-xs">
				<div class="opacity-60 font-mono mb-1">{m.role}</div>
				<div class="whitespace-pre-wrap font-mono">{m.text}</div>
				{#if m.tools && m.tools.length}
					<div class="mt-2 space-y-2">
						{#each m.tools as t}
							<details class="rounded border border-neutral-800 p-2">
								<summary class="cursor-pointer font-mono">
									<span class="text-blue-400">{t.name}</span>
									<span class="opacity-60">
										({Object.keys((t.input as Record<string, unknown>) ?? {}).join(', ')})
									</span>
								</summary>
								<pre class="mt-1 text-[10px] opacity-70 whitespace-pre-wrap">{JSON.stringify(t.input, null, 2)}</pre>
								{#if t.result}
									<pre
										class="mt-1 text-[10px] whitespace-pre-wrap {t.is_error ? 'text-red-400' : ''}"
									>{t.result}</pre>
								{/if}
							</details>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
		{#if busy}
			<div class="text-xs opacity-50 font-mono">…</div>
		{/if}
	</div>

	{#if error}
		<div class="mb-2 text-xs text-red-400 font-mono">{error}</div>
	{/if}

	<div class="mt-3 flex gap-2">
		<textarea
			bind:value={input}
			onkeydown={keydown}
			rows="3"
			placeholder="Message (⌘/Ctrl+Enter to send)"
			class="flex-1 rounded border border-neutral-700 bg-neutral-900 p-2 font-mono text-xs"
		></textarea>
		<button
			onclick={send}
			disabled={busy}
			class="rounded bg-blue-600 px-3 py-1 text-xs font-medium hover:bg-blue-500 disabled:opacity-50 self-end"
		>
			{busy ? '…' : 'Send'}
		</button>
	</div>
</div>

<script lang="ts">
	interface ChatMsg {
		role: 'user' | 'assistant';
		text: string;
		tools?: { name: string; input: unknown; result?: string; is_error?: boolean }[];
	}

	interface ChatSession {
		id: string; // client-side chat id
		backend_session_id: string | null; // server-side workspace session
		runtime: string | null;
		title: string;
		created_at: number;
		messages: ChatMsg[];
	}

	let { workspaceId }: { workspaceId: string } = $props();

	const storageKey = $derived(`vfs-workspace:${workspaceId}:sessions`);
	const activeKey = $derived(`vfs-workspace:${workspaceId}:active-session`);

	let sessions = $state<ChatSession[]>([]);
	let activeId = $state<string | null>(null);
	let input = $state('');
	let busy = $state(false);
	let starting = $state(false);
	let error = $state<string | null>(null);
	let loaded = false;

	const active = $derived(sessions.find((s) => s.id === activeId) ?? null);

	function loadSessions() {
		try {
			const raw = localStorage.getItem(storageKey);
			sessions = raw ? JSON.parse(raw) : [];
			activeId = localStorage.getItem(activeKey);
			if (!sessions.find((s) => s.id === activeId)) {
				activeId = sessions[0]?.id ?? null;
			}
		} catch {
			sessions = [];
			activeId = null;
		}
	}

	function persistSessions() {
		try {
			localStorage.setItem(storageKey, JSON.stringify(sessions));
			if (activeId) localStorage.setItem(activeKey, activeId);
			else localStorage.removeItem(activeKey);
		} catch {}
	}

	async function newSession() {
		starting = true;
		error = null;
		try {
			const res = await fetch('/api/session', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: 'start' })
			});
			if (!res.ok) throw new Error(`session start: HTTP ${res.status}`);
			const body = await res.json();
			if (body.error) throw new Error(String(body.error));
			const s: ChatSession = {
				id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
				backend_session_id: String(body.session_id),
				runtime: String(body.runtime ?? ''),
				title: 'New session',
				created_at: Date.now(),
				messages: []
			};
			sessions = [s, ...sessions];
			activeId = s.id;
			persistSessions();
		} catch (e) {
			error = String(e);
		} finally {
			starting = false;
		}
	}

	async function deleteSession(id: string) {
		const s = sessions.find((x) => x.id === id);
		if (!s) return;
		sessions = sessions.filter((x) => x.id !== id);
		if (activeId === id) activeId = sessions[0]?.id ?? null;
		persistSessions();
		if (s.backend_session_id) {
			fetch('/api/session', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: 'stop', session_id: s.backend_session_id })
			}).catch(() => undefined);
		}
	}

	function selectSession(id: string) {
		activeId = id;
		persistSessions();
	}

	function updateTitle(session: ChatSession) {
		const firstUser = session.messages.find((m) => m.role === 'user');
		if (firstUser) {
			session.title =
				firstUser.text.slice(0, 40) + (firstUser.text.length > 40 ? '…' : '');
		}
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		loadSessions();
		if (!activeId) newSession();
	});

	async function send() {
		if (!input.trim() || busy || !active || !active.backend_session_id) return;
		error = null;
		busy = true;
		const userMsg: ChatMsg = { role: 'user', text: input.trim() };
		active.messages = [...active.messages, userMsg];
		input = '';
		updateTitle(active);

		const assistantMsg: ChatMsg = { role: 'assistant', text: '', tools: [] };
		active.messages = [...active.messages, assistantMsg];
		persistSessions();

		try {
			const wire = active.messages
				.slice(0, -1)
				.map((m) => ({ role: m.role, content: m.text }));
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					messages: wire,
					session_id: active.backend_session_id
				})
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
					const last = active.messages[active.messages.length - 1];
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
					active.messages = [...active.messages];
				}
			}
		} catch (e) {
			error = String(e);
		} finally {
			busy = false;
			persistSessions();
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
	<div class="mb-2 flex items-center gap-1 border-b border-neutral-800 pb-2">
		<select
			value={activeId ?? ''}
			onchange={(e) => selectSession((e.currentTarget as HTMLSelectElement).value)}
			class="flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs font-mono"
		>
			{#each sessions as s}
				<option value={s.id}>{s.title}</option>
			{/each}
		</select>
		<button
			onclick={() => newSession()}
			disabled={starting}
			title="New session (spawns a fresh workspace session)"
			class="rounded bg-neutral-800 px-2 py-1 text-xs hover:bg-neutral-700 disabled:opacity-50"
		>
			{starting ? '…' : '+ New'}
		</button>
		{#if active && sessions.length > 1}
			<button
				onclick={() => active && deleteSession(active.id)}
				title="Delete current session (stops workspace session)"
				class="rounded bg-neutral-800 px-2 py-1 text-xs hover:bg-red-900"
			>
				×
			</button>
		{/if}
	</div>

	{#if active}
		<div class="mb-2 flex items-center gap-2 text-[10px] font-mono opacity-60">
			<span>session:</span>
			<code>{active.backend_session_id ?? '(pending)'}</code>
			{#if active.runtime}
				<span class="rounded bg-neutral-800 px-1.5 py-0.5">{active.runtime}</span>
			{/if}
		</div>
	{/if}

	<div class="flex-1 overflow-y-auto space-y-3 pr-1 min-h-0">
		{#if active}
			{#each active.messages as m}
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
									<pre
										class="mt-1 text-[10px] opacity-70 whitespace-pre-wrap"
									>{JSON.stringify(t.input, null, 2)}</pre>
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
		{/if}
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
			placeholder={active?.backend_session_id
				? 'Message (⌘/Ctrl+Enter to send)'
				: 'Waiting for session…'}
			disabled={!active?.backend_session_id}
			class="flex-1 rounded border border-neutral-700 bg-neutral-900 p-2 font-mono text-xs disabled:opacity-50"
		></textarea>
		<button
			onclick={send}
			disabled={busy || !active?.backend_session_id}
			class="rounded bg-blue-600 px-3 py-1 text-xs font-medium hover:bg-blue-500 disabled:opacity-50 self-end"
		>
			{busy ? '…' : 'Send'}
		</button>
	</div>
</div>

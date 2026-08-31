<script lang="ts">
	import { tick } from 'svelte';

	type TextPart = { type: 'text'; text: string };
	type ToolPart = {
		type: 'tool';
		id?: string;
		name: string;
		input: unknown;
		result?: string;
		is_error?: boolean;
	};
	type Part = TextPart | ToolPart;

	interface ChatMsg {
		role: 'user' | 'assistant';
		text?: string; // legacy fallback
		tools?: { name: string; input: unknown; result?: string; is_error?: boolean }[]; // legacy
		parts?: Part[];
	}

	interface ChatSession {
		id: string;
		backend_session_id: string | null;
		runtime: string | null;
		title: string;
		created_at: number;
		messages: ChatMsg[];
	}

	let {
		workspaceId,
		runtime,
		mountName,
		onAgentMutation
	}: {
		workspaceId: string;
		runtime: string;
		mountName: string;
		onAgentMutation?: () => void;
	} = $props();

	const storageKey = $derived(`vfs-workspace:${workspaceId}:sessions`);
	const activeKey = $derived(`vfs-workspace:${workspaceId}:active-session`);

	let sessions = $state<ChatSession[]>([]);
	let activeId = $state<string | null>(null);
	let input = $state('');
	let busy = $state(false);
	let starting = $state(false);
	let error = $state<string | null>(null);
	let loaded = false;

	let scrollEl = $state<HTMLDivElement | null>(null);
	let stickToBottom = $state(true);
	let showJump = $state(false);
	let textareaEl = $state<HTMLTextAreaElement | null>(null);

	const active = $derived(sessions.find((s) => s.id === activeId) ?? null);

	function migrateMessage(m: ChatMsg): ChatMsg {
		if (m.parts && m.parts.length) return m;
		if (m.role !== 'assistant') return { ...m, parts: m.text ? [{ type: 'text', text: m.text }] : [] };
		const parts: Part[] = [];
		if (m.text) parts.push({ type: 'text', text: m.text });
		if (m.tools) for (const t of m.tools) parts.push({ type: 'tool', ...t });
		return { ...m, parts };
	}

	function migrateSession(s: ChatSession): ChatSession {
		return { ...s, messages: s.messages.map(migrateMessage) };
	}

	function loadSessions() {
		try {
			const raw = localStorage.getItem(storageKey);
			const parsed: ChatSession[] = raw ? JSON.parse(raw) : [];
			sessions = parsed.map(migrateSession);
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
				body: JSON.stringify({ action: 'start', workspace_id: workspaceId })
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
				body: JSON.stringify({
					action: 'stop',
					workspace_id: workspaceId,
					session_id: s.backend_session_id
				})
			}).catch(() => undefined);
		}
	}

	function selectSession(id: string) {
		activeId = id;
		persistSessions();
		stickToBottom = true;
		scheduleScroll();
	}

	function updateTitle(session: ChatSession) {
		const firstUser = session.messages.find((m) => m.role === 'user');
		if (firstUser) {
			const t = firstUser.text ?? (firstUser.parts?.[0]?.type === 'text' ? firstUser.parts[0].text : '');
			session.title = t.slice(0, 40) + (t.length > 40 ? '…' : '');
		}
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		loadSessions();
		if (!activeId) newSession();
	});

	function appendText(msg: ChatMsg, delta: string) {
		const parts = (msg.parts ??= []);
		const last = parts[parts.length - 1];
		if (last && last.type === 'text') last.text += delta;
		else parts.push({ type: 'text', text: delta });
	}

	function appendToolUse(msg: ChatMsg, ev: { id?: string; name: string; input: unknown }) {
		const parts = (msg.parts ??= []);
		parts.push({ type: 'tool', id: ev.id, name: ev.name, input: ev.input });
	}

	function fillToolResult(
		msg: ChatMsg,
		ev: { tool_use_id?: string; text: string; is_error?: boolean }
	) {
		const parts = msg.parts ?? [];
		let target: ToolPart | undefined;
		if (ev.tool_use_id) {
			target = parts.find(
				(p): p is ToolPart => p.type === 'tool' && p.id === ev.tool_use_id
			);
		}
		if (!target) {
			for (let i = parts.length - 1; i >= 0; i--) {
				const p = parts[i];
				if (p.type === 'tool' && p.result === undefined) {
					target = p;
					break;
				}
			}
		}
		if (target) {
			target.result = ev.text;
			target.is_error = ev.is_error;
		}
	}

	async function send() {
		if (!input.trim() || busy || !active || !active.backend_session_id) return;
		error = null;
		busy = true;
		const userMsg: ChatMsg = { role: 'user', parts: [{ type: 'text', text: input.trim() }] };
		userMsg.text = input.trim();
		active.messages = [...active.messages, userMsg];
		input = '';
		autoGrow();
		updateTitle(active);
		stickToBottom = true;

		const assistantMsg: ChatMsg = { role: 'assistant', parts: [] };
		active.messages = [...active.messages, assistantMsg];
		persistSessions();
		scheduleScroll();

		try {
			const wire = active.messages
				.slice(0, -1)
				.map((m) => {
					const text =
						m.text ??
						(m.parts ?? [])
							.filter((p): p is TextPart => p.type === 'text')
							.map((p) => p.text)
							.join('');
					return { role: m.role, content: text };
				});
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					messages: wire,
					workspace_id: workspaceId,
					session_id: active.backend_session_id,
					runtime,
					mount_name: mountName
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
						appendText(last, payload.text);
						last.text = (last.parts ?? [])
							.filter((p): p is TextPart => p.type === 'text')
							.map((p) => p.text)
							.join('\n');
					} else if (payload.type === 'tool_use') {
						appendToolUse(last, { id: payload.tool_use_id, name: payload.name, input: payload.input });
					} else if (payload.type === 'tool_result') {
						fillToolResult(last, {
							tool_use_id: payload.tool_use_id,
							text: payload.text,
							is_error: payload.is_error
						});
						if (!payload.is_error && isMutatingTool(payload.name)) {
							onAgentMutation?.();
						}
					} else if (payload.type === 'error') {
						error = payload.message;
					}
					active.messages = [...active.messages];
					scheduleScroll();
				}
			}
		} catch (e) {
			error = String(e);
		} finally {
			busy = false;
			persistSessions();
			scheduleScroll();
		}
	}

	function keydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			if (e.ctrlKey || e.metaKey) {
				// newline: let default insert
				return;
			}
			if (e.shiftKey) return;
			e.preventDefault();
			send();
		}
	}

	function autoGrow() {
		const el = textareaEl;
		if (!el) return;
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 200) + 'px';
	}

	function onInput() {
		autoGrow();
	}

	async function scheduleScroll() {
		if (!stickToBottom) return;
		await tick();
		const el = scrollEl;
		if (!el) return;
		el.scrollTop = el.scrollHeight;
	}

	function onScroll() {
		const el = scrollEl;
		if (!el) return;
		const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
		stickToBottom = distance < 40;
		showJump = !stickToBottom;
	}

	function jumpToBottom() {
		stickToBottom = true;
		scheduleScroll();
	}

	function fmtArgs(input: unknown): string {
		if (!input || typeof input !== 'object') return '';
		return Object.keys(input as Record<string, unknown>).join(', ');
	}

	function isPart(x: unknown): x is Part {
		return !!x && typeof x === 'object' && 'type' in (x as object);
	}

	const MUTATING_TOOLS = new Set([
		'write',
		'delete',
		'execute_code',
		'execute_command',
		'wait_task'
	]);
	function isMutatingTool(name: string | undefined): boolean {
		return !!name && MUTATING_TOOLS.has(name);
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
			title="New session"
			class="rounded bg-neutral-800 px-2 py-1 text-xs hover:bg-neutral-700 disabled:opacity-50"
		>
			{starting ? '…' : '+ New'}
		</button>
		{#if active && sessions.length > 1}
			<button
				onclick={() => active && deleteSession(active.id)}
				title="Delete session"
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

	<div class="relative flex-1 min-h-0">
		<div
			bind:this={scrollEl}
			onscroll={onScroll}
			class="absolute inset-0 overflow-y-auto space-y-3 pr-1"
		>
			{#if active && active.messages.length === 0}
				<div class="flex flex-col items-center justify-center h-full text-xs opacity-40 font-mono">
					<div class="text-2xl mb-2">✱</div>
					<div>Ask anything about this workspace.</div>
				</div>
			{/if}

			{#if active}
				{#each active.messages as m, i (i)}
					<div
						class="rounded-lg px-3 py-2 text-xs
							{m.role === 'user'
								? 'bg-neutral-800/60 border border-neutral-700'
								: 'bg-neutral-900 border border-neutral-800'}"
					>
						<div class="mb-1 flex items-center gap-2">
							<span
								class="text-[10px] font-mono uppercase tracking-wider {m.role === 'user'
									? 'text-blue-400'
									: 'text-emerald-400'}"
							>
								{m.role === 'user' ? '▸ you' : '● claude'}
							</span>
						</div>

						{#if m.parts && m.parts.length}
							<div class="space-y-2">
								{#each m.parts as part, pi (pi)}
									{#if isPart(part) && part.type === 'text'}
										{#if part.text}
											<div class="whitespace-pre-wrap font-mono leading-relaxed">{part.text}</div>
										{/if}
									{:else if isPart(part) && part.type === 'tool'}
										<details
											class="rounded border border-neutral-800 bg-neutral-950/50"
											open={part.is_error}
										>
											<summary class="cursor-pointer px-2 py-1 font-mono text-[11px] flex items-center gap-2">
												<span class="opacity-50">⚙</span>
												<span class="text-purple-400">{part.name}</span>
												<span class="opacity-50">({fmtArgs(part.input)})</span>
												{#if part.result === undefined}
													<span class="ml-auto text-[10px] opacity-50 animate-pulse">running…</span>
												{:else if part.is_error}
													<span class="ml-auto text-[10px] text-red-400">error</span>
												{:else}
													<span class="ml-auto text-[10px] text-emerald-500 opacity-70">✓</span>
												{/if}
											</summary>
											<div class="px-2 py-1 border-t border-neutral-800">
												<div class="text-[10px] opacity-40 mb-0.5">args</div>
												<pre class="text-[10px] opacity-80 whitespace-pre-wrap">{JSON.stringify(
														part.input,
														null,
														2
													)}</pre>
												{#if part.result !== undefined}
													<div class="text-[10px] opacity-40 mt-1 mb-0.5">result</div>
													<pre
														class="text-[10px] whitespace-pre-wrap max-h-64 overflow-auto {part.is_error
															? 'text-red-400'
															: 'text-neutral-300'}"
													>{part.result}</pre>
												{/if}
											</div>
										</details>
									{/if}
								{/each}
							</div>
						{:else if m.text}
							<div class="whitespace-pre-wrap font-mono leading-relaxed">{m.text}</div>
						{/if}
					</div>
				{/each}
			{/if}
			{#if busy}
				<div class="text-xs opacity-50 font-mono flex items-center gap-1 px-1">
					<span class="animate-pulse">●</span>
					<span>thinking</span>
				</div>
			{/if}
		</div>

		{#if showJump}
			<button
				type="button"
				onclick={jumpToBottom}
				class="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-neutral-700 bg-neutral-900 px-3 py-1 text-[11px] shadow hover:bg-neutral-800"
			>
				↓ new messages
			</button>
		{/if}
	</div>

	{#if error}
		<div class="mt-2 text-xs text-red-400 font-mono">{error}</div>
	{/if}

	<div class="mt-3 flex gap-2 items-end">
		<textarea
			bind:this={textareaEl}
			bind:value={input}
			oninput={onInput}
			onkeydown={keydown}
			rows="1"
			placeholder={active?.backend_session_id
				? 'Message  (Enter to send, Ctrl+Enter for newline)'
				: 'Waiting for session…'}
			disabled={!active?.backend_session_id}
			class="flex-1 resize-none rounded border border-neutral-700 bg-neutral-900 p-2 font-mono text-xs disabled:opacity-50 focus:border-blue-500 focus:outline-none"
			style="min-height: 2.25rem; max-height: 200px;"
		></textarea>
		<button
			onclick={send}
			disabled={busy || !active?.backend_session_id || !input.trim()}
			class="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium hover:bg-blue-500 disabled:opacity-40"
		>
			{busy ? '…' : 'Send'}
		</button>
	</div>
</div>

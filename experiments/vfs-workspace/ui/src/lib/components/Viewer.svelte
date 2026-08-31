<script lang="ts">
	import { marked } from 'marked';
	import { api } from '$lib/api';
	import TipTapEditor from './TipTapEditor.svelte';

	let {
		workspaceId,
		path,
		onSaved
	}: { workspaceId: string; path: string; onSaved?: (path: string) => void } = $props();

	type Kind = 'pdf' | 'html' | 'md' | 'image' | 'text' | 'code' | 'binary';

	const CODE_EXT = new Set([
		'js','jsx','ts','tsx','py','rb','go','rs','java','c','h','cpp','hpp','cs','sh','bash',
		'zsh','yml','yaml','toml','json','xml','sql','swift','kt','php','lua','r','scala'
	]);
	const TEXT_EXT = new Set(['txt','log','env','ini','cfg','conf']);
	const IMG_EXT = new Set(['png','jpg','jpeg','gif','webp','svg','bmp','ico']);

	function ext(p: string): string {
		const s = p.split('/').pop() ?? '';
		const i = s.lastIndexOf('.');
		return i < 0 ? '' : s.slice(i + 1).toLowerCase();
	}

	function classify(p: string): Kind {
		const e = ext(p);
		if (e === 'pdf') return 'pdf';
		if (e === 'html' || e === 'htm') return 'html';
		if (e === 'md' || e === 'markdown') return 'md';
		if (IMG_EXT.has(e)) return 'image';
		if (CODE_EXT.has(e)) return 'code';
		if (TEXT_EXT.has(e) || e === '') return 'text';
		return 'binary';
	}

	const kind = $derived(classify(path));
	const editable = $derived(kind === 'md' || kind === 'html' || kind === 'text' || kind === 'code');
	const editorMode = $derived(kind === 'md' ? 'md' : kind === 'html' ? 'html' : 'txt');

	let rawText = $state<string | null>(null);
	let blobUrl = $state<string | null>(null);
	let loadError = $state<string | null>(null);
	let loading = $state(false);

	let editing = $state(false);
	let draft = $state('');
	let dirty = $state(false);
	let saving = $state(false);
	let saveError = $state<string | null>(null);

	let currentBlobUrl: string | null = null;

	function resetState() {
		rawText = null;
		if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
		currentBlobUrl = null;
		blobUrl = null;
		loadError = null;
		editing = false;
		draft = '';
		dirty = false;
		saveError = null;
	}

	$effect(() => {
		if (!path) return;
		resetState();
		loading = true;
		const k = classify(path);
		const p = path;
		(async () => {
			try {
				if (k === 'pdf' || k === 'image' || k === 'binary') {
					const blob = await api.readBlob(workspaceId, p);
					if (p !== path) return;
					const type =
						k === 'pdf' ? 'application/pdf' : k === 'image' ? blob.type || `image/${ext(p)}` : blob.type;
					const typed = new Blob([blob], { type });
					const url = URL.createObjectURL(typed);
					currentBlobUrl = url;
					blobUrl = url;
				} else {
					const t = await api.readFile(workspaceId, p);
					if (p !== path) return;
					rawText = t as string;
					draft = t as string;
				}
			} catch (e) {
				loadError = String(e);
			} finally {
				loading = false;
			}
		})();
	});

	function onEdit() {
		if (rawText === null) return;
		draft = rawText;
		dirty = false;
		editing = true;
	}

	function onCancel() {
		if (dirty && !confirm('Discard unsaved changes?')) return;
		editing = false;
		draft = rawText ?? '';
		dirty = false;
	}

	async function onSave() {
		if (!dirty || saving) return;
		saving = true;
		saveError = null;
		try {
			await api.writeFile(workspaceId, path, draft);
			rawText = draft;
			dirty = false;
			onSaved?.(path);
		} catch (e) {
			saveError = String(e);
		} finally {
			saving = false;
		}
	}

	function onEditorChange(v: string) {
		draft = v;
		dirty = v !== (rawText ?? '');
	}

	const renderedMd = $derived(kind === 'md' && rawText !== null ? marked.parse(rawText) : '');
</script>

<div class="flex flex-col gap-2 h-full">
	<div class="flex items-center gap-2 text-xs font-mono">
		<span class="opacity-60 truncate">{path}</span>
		<span class="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] uppercase opacity-80">{kind}</span>
		<div class="ml-auto flex items-center gap-1">
			{#if editable && !editing}
				<button
					type="button"
					class="rounded border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800"
					onclick={onEdit}
					disabled={rawText === null}
				>
					Edit
				</button>
			{/if}
			{#if editing}
				<button
					type="button"
					class="rounded border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800"
					onclick={onCancel}
				>
					Cancel
				</button>
				<button
					type="button"
					class="rounded border border-blue-600 bg-blue-700 px-2 py-0.5 text-white disabled:opacity-40"
					onclick={onSave}
					disabled={!dirty || saving}
				>
					{saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
				</button>
			{/if}
		</div>
	</div>

	{#if saveError}
		<div class="text-xs font-mono text-red-400">save: {saveError}</div>
	{/if}

	<div class="flex-1 min-h-0 overflow-auto">
		{#if loading}
			<div class="text-xs opacity-50">Loading…</div>
		{:else if loadError}
			<div class="text-xs font-mono text-red-400">{loadError}</div>
		{:else if editing}
			<TipTapEditor content={draft} mode={editorMode} onChange={onEditorChange} />
		{:else if kind === 'pdf' && blobUrl}
			<iframe src={blobUrl} title={path} class="w-full h-full min-h-96 rounded border border-neutral-800"></iframe>
		{:else if kind === 'image' && blobUrl}
			<img src={blobUrl} alt={path} class="max-w-full h-auto rounded border border-neutral-800" />
		{:else if kind === 'binary'}
			<div class="text-xs opacity-60">Binary file — no preview.</div>
		{:else if kind === 'html' && rawText !== null}
			<iframe
				srcdoc={rawText}
				title={path}
				class="w-full h-full min-h-96 rounded border border-neutral-800 bg-white"
				sandbox="allow-same-origin"
			></iframe>
		{:else if kind === 'md' && rawText !== null}
			<div class="prose prose-invert markdown-body">{@html renderedMd}</div>
		{:else if rawText !== null}
			<pre class="whitespace-pre-wrap font-mono text-xs">{rawText}</pre>
		{/if}
	</div>
</div>

<style>
	:global(.markdown-body) {
		font-size: 0.875rem;
		line-height: 1.5;
	}
	:global(.markdown-body h1) {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0.5rem 0;
	}
	:global(.markdown-body h2) {
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0.5rem 0;
	}
	:global(.markdown-body h3) {
		font-size: 1.1rem;
		font-weight: 600;
		margin: 0.5rem 0;
	}
	:global(.markdown-body pre) {
		background: #0b0f19;
		padding: 0.75rem;
		border-radius: 0.375rem;
		overflow-x: auto;
		font-size: 12px;
	}
	:global(.markdown-body code) {
		background: #1f2937;
		padding: 0 0.25rem;
		border-radius: 3px;
		font-size: 0.9em;
	}
	:global(.markdown-body pre code) {
		background: transparent;
		padding: 0;
	}
	:global(.markdown-body ul) {
		list-style: disc;
		padding-left: 1.25rem;
	}
	:global(.markdown-body ol) {
		list-style: decimal;
		padding-left: 1.25rem;
	}
	:global(.markdown-body a) {
		color: #60a5fa;
		text-decoration: underline;
	}
	:global(.markdown-body blockquote) {
		border-left: 3px solid #374151;
		padding-left: 0.75rem;
		color: #9ca3af;
	}
</style>

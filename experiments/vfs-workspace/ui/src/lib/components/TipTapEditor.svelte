<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { Editor } from '@tiptap/core';
	import StarterKit from '@tiptap/starter-kit';
	import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight';
	import { common, createLowlight } from 'lowlight';
	import { Markdown } from 'tiptap-markdown';

	type Mode = 'md' | 'html' | 'txt';

	let {
		content,
		mode,
		onChange
	}: {
		content: string;
		mode: Mode;
		onChange: (value: string) => void;
	} = $props();

	let host = $state<HTMLDivElement | null>(null);
	let editor = $state<Editor | null>(null);
	let lastLoaded = '';

	const lowlight = createLowlight(common);

	function loadContent(text: string) {
		if (!editor) return;
		lastLoaded = text;
		if (mode === 'md' || mode === 'html') {
			editor.commands.setContent(text || '', { emitUpdate: false });
		} else {
			editor.commands.setContent(
				{ type: 'doc', content: text ? [{ type: 'paragraph', content: [{ type: 'text', text }] }] : [] },
				{ emitUpdate: false }
			);
		}
	}

	onMount(() => {
		if (!host) return;
		const extensions: any[] = [
			StarterKit.configure({ codeBlock: false }),
			CodeBlockLowlight.configure({ lowlight })
		];
		if (mode === 'md') extensions.push(Markdown.configure({ html: false, linkify: true, breaks: false }));

		editor = new Editor({
			element: host,
			extensions,
			editorProps: {
				attributes: {
					class: 'tiptap-body focus:outline-none min-h-40 max-w-none'
				}
			},
			onUpdate: ({ editor: e }) => {
				let v = '';
				if (mode === 'md') v = (e.storage as any).markdown.getMarkdown();
				else if (mode === 'html') v = e.getHTML();
				else v = e.getText();
				onChange(v);
			}
		});
		loadContent(content);
	});

	$effect(() => {
		if (editor && content !== lastLoaded) loadContent(content);
	});

	onDestroy(() => editor?.destroy());

	function toolBtn(label: string, active: boolean, action: () => void) {
		return { label, active, action };
	}

	const buttons = $derived(
		editor
			? [
					toolBtn('B', editor.isActive('bold'), () => editor!.chain().focus().toggleBold().run()),
					toolBtn('I', editor.isActive('italic'), () => editor!.chain().focus().toggleItalic().run()),
					toolBtn('H1', editor.isActive('heading', { level: 1 }), () =>
						editor!.chain().focus().toggleHeading({ level: 1 }).run()
					),
					toolBtn('H2', editor.isActive('heading', { level: 2 }), () =>
						editor!.chain().focus().toggleHeading({ level: 2 }).run()
					),
					toolBtn('•', editor.isActive('bulletList'), () =>
						editor!.chain().focus().toggleBulletList().run()
					),
					toolBtn('1.', editor.isActive('orderedList'), () =>
						editor!.chain().focus().toggleOrderedList().run()
					),
					toolBtn('“', editor.isActive('blockquote'), () =>
						editor!.chain().focus().toggleBlockquote().run()
					),
					toolBtn('<>', editor.isActive('code'), () => editor!.chain().focus().toggleCode().run()),
					toolBtn('{}', editor.isActive('codeBlock'), () =>
						editor!.chain().focus().toggleCodeBlock().run()
					)
			  ]
			: []
	);
</script>

<div class="flex flex-col gap-2">
	<div class="flex flex-wrap gap-1">
		{#each buttons as b}
			<button
				type="button"
				onclick={b.action}
				class="rounded border border-neutral-700 px-1.5 py-0.5 text-[11px] font-mono hover:bg-neutral-800"
				class:bg-neutral-800={b.active}
			>
				{b.label}
			</button>
		{/each}
	</div>
	<div bind:this={host} class="rounded border border-neutral-800 p-2 text-sm"></div>
</div>

<style>
	:global(.tiptap-body) {
		min-height: 12rem;
	}
	:global(.tiptap-body pre) {
		background: #0b0f19;
		color: #e5e7eb;
		padding: 0.75rem;
		border-radius: 0.375rem;
		overflow-x: auto;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 12px;
	}
	:global(.tiptap-body code) {
		background: #1f2937;
		padding: 0 0.25rem;
		border-radius: 3px;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.9em;
	}
	:global(.tiptap-body pre code) {
		background: transparent;
		padding: 0;
	}
	:global(.tiptap-body h1) {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0.5rem 0;
	}
	:global(.tiptap-body h2) {
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0.5rem 0;
	}
	:global(.tiptap-body ul) {
		list-style: disc;
		padding-left: 1.25rem;
	}
	:global(.tiptap-body ol) {
		list-style: decimal;
		padding-left: 1.25rem;
	}
	:global(.tiptap-body blockquote) {
		border-left: 3px solid #374151;
		padding-left: 0.75rem;
		color: #9ca3af;
	}
	:global(.tiptap-body .hljs-keyword) {
		color: #c586c0;
	}
	:global(.tiptap-body .hljs-string) {
		color: #ce9178;
	}
	:global(.tiptap-body .hljs-comment) {
		color: #6a9955;
		font-style: italic;
	}
	:global(.tiptap-body .hljs-number) {
		color: #b5cea8;
	}
	:global(.tiptap-body .hljs-function),
	:global(.tiptap-body .hljs-title) {
		color: #dcdcaa;
	}
	:global(.tiptap-body .hljs-variable),
	:global(.tiptap-body .hljs-attr) {
		color: #9cdcfe;
	}
	:global(.tiptap-body .hljs-built_in) {
		color: #4ec9b0;
	}
</style>

<script lang="ts" module>
	export interface MenuItem {
		label: string;
		onClick: () => void;
		danger?: boolean;
		disabled?: boolean;
	}
</script>

<script lang="ts">
	let {
		open,
		x,
		y,
		items,
		onClose
	}: {
		open: boolean;
		x: number;
		y: number;
		items: MenuItem[];
		onClose: () => void;
	} = $props();

	function handleGlobalClick() {
		if (open) onClose();
	}

	function handleKey(e: KeyboardEvent) {
		if (open && e.key === 'Escape') onClose();
	}

	function pick(item: MenuItem) {
		if (item.disabled) return;
		onClose();
		item.onClick();
	}
</script>

<svelte:window onclick={handleGlobalClick} oncontextmenu={handleGlobalClick} onkeydown={handleKey} />

{#if open}
	<div
		role="menu"
		tabindex="-1"
		class="fixed z-50 min-w-40 rounded border border-neutral-700 bg-neutral-900 shadow-lg text-xs"
		style="left: {x}px; top: {y}px"
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => e.stopPropagation()}
		oncontextmenu={(e) => {
			e.preventDefault();
			e.stopPropagation();
		}}
	>
		{#each items as item}
			<button
				type="button"
				class="block w-full text-left px-3 py-1.5 hover:bg-neutral-800 disabled:opacity-40"
				class:text-red-400={item.danger}
				disabled={item.disabled}
				onclick={() => pick(item)}
			>
				{item.label}
			</button>
		{/each}
	</div>
{/if}

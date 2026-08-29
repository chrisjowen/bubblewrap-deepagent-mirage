<script lang="ts">
	import '../app.css';
	let { children } = $props();
</script>

<div class="min-h-screen bg-neutral-950 text-neutral-100">
	<header class="border-b border-neutral-800 px-4 py-3 font-mono text-sm">
		<a href="/" class="hover:opacity-70">vfs-workspace</a>
	</header>
	<main class="p-4">
		{@render children()}
	</main>
</div>

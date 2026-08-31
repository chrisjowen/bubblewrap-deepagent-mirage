/**
 * Force-load monorepo root .env with override.
 *
 * SvelteKit / Vite defer to inherited process env, so a pre-set
 * ANTHROPIC_API_KEY in ~/.zshrc or a wrapper `KEY=$KEY pnpm dev`
 * line wins over what's in .env. We explicitly re-load the root
 * .env with override:true so the file is the source of truth.
 *
 * Import as a side-effect from any server module reading env.
 */

import { config } from 'dotenv';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

function findRootEnv(start: string): string | null {
	let dir = start;
	for (let i = 0; i < 10; i++) {
		const candidate = resolve(dir, '.env');
		if (existsSync(candidate)) return candidate;
		const parent = dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
	return null;
}

const envPath = findRootEnv(process.cwd());

if (envPath) {
	config({ path: envPath, override: true, quiet: true });
	// eslint-disable-next-line no-console
	console.log(`[env] loaded ${envPath}`);
} else {
	// eslint-disable-next-line no-console
	console.warn(`[env] no .env found walking up from ${process.cwd()}`);
}

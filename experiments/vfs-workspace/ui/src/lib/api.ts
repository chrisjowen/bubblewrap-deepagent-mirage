import { env } from '$env/dynamic/public';

const BASE = env.PUBLIC_API_BASE ?? 'http://127.0.0.1:8100';
const USER = env.PUBLIC_USER_ID ?? 'chris';

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		...init,
		headers: { 'X-User-Id': USER, ...(init.headers ?? {}) }
	});
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const body = await res.text();
			detail = body || detail;
		} catch {}
		throw new Error(`${res.status} ${detail}`);
	}
	const ct = res.headers.get('content-type') ?? '';
	return ct.includes('application/json') ? res.json() : ((await res.text()) as unknown as T);
}

async function reqRaw(path: string, init: RequestInit = {}): Promise<Response> {
	const res = await fetch(`${BASE}${path}`, {
		...init,
		headers: { 'X-User-Id': USER, ...(init.headers ?? {}) }
	});
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.text()) || detail;
		} catch {}
		throw new Error(`${res.status} ${detail}`);
	}
	return res;
}

export interface Workspace {
	id: string;
	label?: string;
	runtime: string;
	mount_name?: string;
}
export interface TreeEntry {
	path: string;
	is_dir: boolean;
	size: number | null;
}
export interface ExecResp {
	stdout: string;
	stderr: string;
	exit_code: number;
	elapsed_ms: number;
}

function filePath(id: string, path: string): string {
	return `/workspaces/${id}/files/${path.replace(/^\//, '')}`;
}

export const api = {
	listWorkspaces: () => req<Workspace[]>('/workspaces'),
	openWorkspace: (id: string) =>
		req<{ status: string; id: string; label: string; runtime: string; mount_name: string }>(
			`/workspaces/${id}/open`,
			{ method: 'POST' }
		),
	tree: (id: string, path = '/', refresh = false) =>
		req<{ entries: TreeEntry[] }>(
			`/workspaces/${id}/tree?path=${encodeURIComponent(path)}${refresh ? '&refresh=true' : ''}`
		),
	readFile: (id: string, path: string) => req<string>(filePath(id, path)),
	readBlob: async (id: string, path: string): Promise<Blob> => {
		const res = await reqRaw(filePath(id, path));
		return res.blob();
	},
	writeFile: async (id: string, path: string, body: string | Blob | ArrayBuffer) => {
		await reqRaw(filePath(id, path), {
			method: 'PUT',
			headers: { 'Content-Type': 'application/octet-stream' },
			body: body as BodyInit
		});
	},
	deleteFile: async (id: string, path: string) => {
		await reqRaw(filePath(id, path), { method: 'DELETE' });
	},
	mkdir: async (id: string, path: string) => {
		await reqRaw(`/workspaces/${id}/mkdir`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ path })
		});
	},
	move: async (id: string, src: string, dst: string) => {
		await reqRaw(`/workspaces/${id}/move`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ src, dst })
		});
	},
	exec: (id: string, body: { language: 'python' | 'node'; code: string }) =>
		req<ExecResp>(`/workspaces/${id}/exec`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		})
};

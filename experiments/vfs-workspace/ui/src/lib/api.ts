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

export interface Workspace {
	id: string;
	runtime: string;
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

export const api = {
	listWorkspaces: () => req<Workspace[]>('/workspaces'),
	openWorkspace: (id: string) =>
		req<{ status: string; runtime: string }>(`/workspaces/${id}/open`, { method: 'POST' }),
	tree: (id: string, path = '/') =>
		req<{ entries: TreeEntry[] }>(`/workspaces/${id}/tree?path=${encodeURIComponent(path)}`),
	readFile: (id: string, path: string) =>
		req<string>(`/workspaces/${id}/files/${path.replace(/^\//, '')}`),
	exec: (id: string, body: { language: 'python' | 'node'; code: string }) =>
		req<ExecResp>(`/workspaces/${id}/exec`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		})
};

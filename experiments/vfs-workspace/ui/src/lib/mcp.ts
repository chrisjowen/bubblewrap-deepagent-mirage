import { env as pubEnv } from '$env/dynamic/public';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const API_BASE = pubEnv.PUBLIC_API_BASE ?? 'http://127.0.0.1:8100';
const USER = pubEnv.PUBLIC_USER_ID ?? 'chris';

export async function openMcp(): Promise<Client> {
	const url = new URL(`${API_BASE}/mcp/`);
	const transport = new StreamableHTTPClientTransport(url, {
		requestInit: { headers: { 'X-User-Id': USER } }
	});
	const client = new Client(
		{ name: 'vfs-workspace-ui', version: '0.1.0' },
		{ capabilities: {} }
	);
	await client.connect(transport);
	return client;
}

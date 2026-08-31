import { openMcp } from '$lib/mcp';
import { json, type RequestHandler } from '@sveltejs/kit';

type Body =
	| { action: 'start'; workspace_id: string }
	| { action: 'stop'; workspace_id: string; session_id: string };

function extractStructured(result: unknown): Record<string, unknown> {
	const r = result as {
		structuredContent?: unknown;
		content?: Array<{ type: string; text?: string }>;
	};
	if (r.structuredContent && typeof r.structuredContent === 'object') {
		return r.structuredContent as Record<string, unknown>;
	}
	const first = r.content?.[0];
	if (first?.type === 'text' && first.text) {
		try {
			return JSON.parse(first.text);
		} catch {
			return { text: first.text };
		}
	}
	return {};
}

export const POST: RequestHandler = async ({ request }) => {
	const body = (await request.json()) as Body;
	if (!body.workspace_id) {
		return json({ error: 'workspace_id required' }, { status: 400 });
	}
	const mcp = await openMcp();
	try {
		if (body.action === 'start') {
			const result = await mcp.callTool({
				name: 'start_session',
				arguments: { workspace_id: body.workspace_id }
			});
			return json(extractStructured(result));
		}
		if (body.action === 'stop') {
			const result = await mcp.callTool({
				name: 'stop_session',
				arguments: { workspace_id: body.workspace_id, session_id: body.session_id }
			});
			return json(extractStructured(result));
		}
		return json({ error: 'unknown action' }, { status: 400 });
	} finally {
		await mcp.close().catch(() => undefined);
	}
};

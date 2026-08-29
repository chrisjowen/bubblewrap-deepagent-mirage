import { env as pubEnv } from '$env/dynamic/public';
import { env as privEnv } from '$env/dynamic/private';
import Anthropic from '@anthropic-ai/sdk';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { RequestHandler } from './$types';

const API_BASE = pubEnv.PUBLIC_API_BASE ?? 'http://127.0.0.1:8100';
const USER = pubEnv.PUBLIC_USER_ID ?? 'chris';
const ANTHROPIC_KEY = privEnv.ANTHROPIC_API_KEY;
const MODEL = privEnv.CHAT_MODEL ?? 'claude-opus-4-7';

interface ChatMessage {
	role: 'user' | 'assistant';
	content: string | Anthropic.ContentBlockParam[];
}

async function openMcpClient(workspaceId: string): Promise<Client> {
	const url = new URL(`${API_BASE}/mcp/workspaces/${workspaceId}/mcp`);
	const transport = new StreamableHTTPClientTransport(url, {
		requestInit: { headers: { 'X-User-Id': USER } }
	});
	const client = new Client({ name: 'vfs-workspace-ui', version: '0.1.0' }, { capabilities: {} });
	await client.connect(transport);
	return client;
}

function mcpToolsToAnthropic(mcpTools: { tools: Array<{ name: string; description?: string; inputSchema: unknown }> }): Anthropic.Tool[] {
	return mcpTools.tools.map((t) => ({
		name: t.name,
		description: t.description ?? '',
		input_schema: t.inputSchema as Anthropic.Tool.InputSchema
	}));
}

export const POST: RequestHandler = async ({ request }) => {
	if (!ANTHROPIC_KEY) {
		return new Response(JSON.stringify({ error: 'ANTHROPIC_API_KEY not set on server' }), {
			status: 500,
			headers: { 'Content-Type': 'application/json' }
		});
	}

	const { workspaceId, messages }: { workspaceId: string; messages: ChatMessage[] } =
		await request.json();

	const anthropic = new Anthropic({ apiKey: ANTHROPIC_KEY });
	const mcp = await openMcpClient(workspaceId);
	const toolsList = await mcp.listTools();
	const tools = mcpToolsToAnthropic(toolsList);

	const encoder = new TextEncoder();
	const stream = new ReadableStream({
		async start(controller) {
			const send = (obj: unknown) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
			const conv: Anthropic.MessageParam[] = messages.map((m) => ({
				role: m.role,
				content: m.content
			})) as Anthropic.MessageParam[];

			try {
				while (true) {
					const response = await anthropic.messages.create({
						model: MODEL,
						max_tokens: 8192,
						system:
							'You are a coding agent operating on the user\'s workspace via MCP tools (read, write, delete, ls, execute). Use the tools to explore, edit, and run code. Confirm intent for destructive operations. Be concise.',
						tools,
						messages: conv
					});

					// Stream any text blocks
					for (const block of response.content) {
						if (block.type === 'text') {
							send({ type: 'text', text: block.text });
						} else if (block.type === 'tool_use') {
							send({ type: 'tool_use', name: block.name, input: block.input });
						}
					}

					if (response.stop_reason !== 'tool_use') {
						send({ type: 'done', stop_reason: response.stop_reason });
						break;
					}

					// Append assistant turn
					conv.push({ role: 'assistant', content: response.content });

					// Execute all tool_use blocks via MCP; collect results
					const toolResults: Anthropic.ToolResultBlockParam[] = [];
					for (const block of response.content) {
						if (block.type !== 'tool_use') continue;
						try {
							const result = await mcp.callTool({
								name: block.name,
								arguments: block.input as Record<string, unknown>
							});
							const blocks = (result.content as Array<Record<string, unknown>> | undefined) ?? [];
							const text = blocks
								.map((c) => (c.type === 'text' ? String(c.text) : JSON.stringify(c)))
								.join('\n');
							send({ type: 'tool_result', tool_use_id: block.id, name: block.name, text });
							toolResults.push({
								type: 'tool_result',
								tool_use_id: block.id,
								content: text
							});
						} catch (exc) {
							const errMsg = String(exc);
							send({ type: 'tool_result', tool_use_id: block.id, name: block.name, text: errMsg, is_error: true });
							toolResults.push({
								type: 'tool_result',
								tool_use_id: block.id,
								content: errMsg,
								is_error: true
							});
						}
					}
					conv.push({ role: 'user', content: toolResults });
				}
			} catch (exc) {
				send({ type: 'error', message: String(exc) });
			} finally {
				await mcp.close().catch(() => undefined);
				controller.close();
			}
		}
	});

	return new Response(stream, {
		headers: {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache',
			Connection: 'keep-alive'
		}
	});
};

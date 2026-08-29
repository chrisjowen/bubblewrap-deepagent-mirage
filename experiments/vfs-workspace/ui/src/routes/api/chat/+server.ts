import { env as privEnv } from '$env/dynamic/private';
import Anthropic from '@anthropic-ai/sdk';
import { openMcp } from '$lib/mcp';
import type { RequestHandler } from './$types';

const ANTHROPIC_KEY = privEnv.ANTHROPIC_API_KEY;
const MODEL = privEnv.CHAT_MODEL ?? 'claude-opus-4-7';

interface ChatMessage {
	role: 'user' | 'assistant';
	content: string | Anthropic.ContentBlockParam[];
}

type McpTool = { name: string; description?: string; inputSchema: unknown };

function toAnthropicTools(list: { tools: McpTool[] }): Anthropic.Tool[] {
	return list.tools.map((t) => ({
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

	const {
		messages,
		session_id
	}: { messages: ChatMessage[]; session_id: string } = await request.json();

	if (!session_id) {
		return new Response(JSON.stringify({ error: 'session_id required' }), {
			status: 400,
			headers: { 'Content-Type': 'application/json' }
		});
	}

	const anthropic = new Anthropic({ apiKey: ANTHROPIC_KEY });
	const mcp = await openMcp();
	const tools = toAnthropicTools(await mcp.listTools());

	const encoder = new TextEncoder();
	const stream = new ReadableStream({
		async start(controller) {
			const send = (obj: unknown) =>
				controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));

			const conv: Anthropic.MessageParam[] = messages.map((m) => ({
				role: m.role,
				content: m.content
			})) as Anthropic.MessageParam[];

			const system =
				`You are a coding agent operating on a remote workspace via MCP tools.\n\n` +
				`CRITICAL: You have NO local filesystem. Do NOT try to access files under /Users, /home, ~/, ./, or any local path. Do NOT think about "downloading" or "uploading" files. Every file lives in the workspace and is accessed through MCP tools.\n\n` +
				`## The workspace\n` +
				`The workspace is a single directory backed by S3. Files under it can be reached two ways:\n` +
				`  1. MCP file tools (\`read\` / \`write\` / \`delete\` / \`ls\`) — paths are RELATIVE to workspace root, e.g. \`read("report.pdf")\`, \`ls("/")\`. No session_id needed.\n` +
				`  2. Inside the session's runtime container, the same workspace is mounted at \`/workspace\`. So \`execute_command("cat /workspace/report.pdf")\` reads the same file.\n` +
				`Both views point at the same underlying storage. Writes through either are visible to the other.\n\n` +
				`## Session context\n` +
				`Your exec session_id is "${session_id}". Pass it to every session-scoped tool (execute_code, execute_command, start_command_execution, get_task, stop_task).\n` +
				`Do NOT call start_session or stop_session — the UI owns session lifecycle.\n\n` +
				`## When to use which tool\n` +
				`- Reading / writing individual files: use \`read\` / \`write\` (simplest).\n` +
				`- Listing directory structure: use \`ls\`.\n` +
				`- Running code that processes many files, or existing scripts: use \`execute_code\` (python/node/bash) or \`execute_command\` (bash), and reference files under \`/workspace/...\`.\n` +
				`- Long-running commands: \`start_command_execution\` → poll with \`get_task\`.\n\n` +
				`Be concise. Confirm intent for destructive operations.`;

			try {
				while (true) {
					const response = await anthropic.messages.create({
						model: MODEL,
						max_tokens: 8192,
						system,
						tools,
						messages: conv
					});

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

					conv.push({ role: 'assistant', content: response.content });

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
							toolResults.push({ type: 'tool_result', tool_use_id: block.id, content: text });
						} catch (exc) {
							const errMsg = String(exc);
							send({
								type: 'tool_result',
								tool_use_id: block.id,
								name: block.name,
								text: errMsg,
								is_error: true
							});
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

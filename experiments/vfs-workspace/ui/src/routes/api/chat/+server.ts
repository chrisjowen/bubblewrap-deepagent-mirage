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
				`You are a coding agent operating a remote sandbox against a separate persistent workspace, both via MCP tools.\n\n` +
				`═══════════════════════════════════════════════════════════════════\n` +
				`CRITICAL — the sandbox and the workspace are TWO SEPARATE THINGS\n` +
				`═══════════════════════════════════════════════════════════════════\n\n` +
				`## Workspace (persistent, S3-backed)\n` +
				`Use: \`read\` / \`write\` / \`delete\` / \`ls\` (no session_id). Paths RELATIVE to workspace root — e.g. \`read("report.pdf")\`, \`ls("/notes/")\`.\n` +
				`\n` +
				`## Exec session (ephemeral sandbox container)\n` +
				`Use: \`execute_code(session_id, code, language)\` and \`execute_command(session_id, command)\` with session_id="${session_id}".\n` +
				`\n` +
				`### The sandbox FS is EMPTY except for its OS. There is NO /workspace directory. Workspace files DO NOT appear here.\n` +
				`- \`cat /workspace/anything\` → will fail. There is no /workspace.\n` +
				`- \`ls /workspace\` → will fail.\n` +
				`- \`python foo.py\` where foo.py lives in the workspace → will fail. The file is not in the sandbox.\n` +
				`\n` +
				`### To run a workspace script or read a workspace file inside the sandbox:\n` +
				`Option A (simplest, one-shot): use MCP tools directly — \`read\` the file, do the work in your reply, or pipe the content through \`execute_code\` inline.\n` +
				`Option B (multi-step): \`read\` the file → in \`execute_code\` build the file inside the sandbox with \`open("/tmp/foo.py","w").write(<content>)\` → run it. Write results back via \`write\`.\n` +
				`Option C (bytes as data): pass file bytes into a Python variable in \`execute_code\` and process directly without touching sandbox FS.\n` +
				`\n` +
				`## Session lifecycle\n` +
				`Your session_id is "${session_id}". Pass it to every session-scoped tool. Do NOT call start_session / stop_session — the UI owns lifecycle.\n` +
				`\n` +
				`## Sandbox runtime\n` +
				`Amazon Linux. Python interpreter is \`python3\` (there is NO \`python\` symlink — always use \`python3\`). Node.js also available. Common data-science + document libs pre-installed: numpy, pandas, scipy, sklearn, matplotlib, pillow, openpyxl, pypdf, pdfplumber, pymupdf (\`import pymupdf\`; \`import fitz\` still works but deprecated), python-docx, python-pptx, requests, boto3. Additional: \`pip install X\`. \`execute_code(language="python")\` runs in a persistent kernel — imports and variables carry across calls in the same session.\n` +
				`\n` +
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

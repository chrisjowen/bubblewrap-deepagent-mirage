import '$lib/server/env';
import Anthropic from '@anthropic-ai/sdk';
import { openMcp } from '$lib/mcp';
import type { RequestHandler } from './$types';

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

function buildSystemPrompt(opts: {
	workspaceId: string;
	sessionId: string;
	runtime: string;
	mountName: string;
}): string {
	const { workspaceId, sessionId, runtime, mountName } = opts;

	const mountLine =
		runtime === 'docker-local'
			? `A local docker container mounts the workspace S3 folder at \`/workspace\` inside the sandbox (mountpoint-s3). Use it for scripts that touch many files: \`ls /workspace\`, \`python3 /workspace/foo.py\`.`
			: `The AWS AgentCore Code Interpreter sandbox may or may not expose a filesystem mount depending on how the interpreter was created. If a mount exists it is typically \`/mnt/s3data\` — verify with \`ls /mnt/s3data\` before using. If no mount, use the MCP file tools exclusively.`;

	return (
		`You are a coding agent operating a persistent workspace.\n\n` +
		`## Identity\n` +
		`- workspace_id: "${workspaceId}"  (mount_name: "/${mountName}")\n` +
		`- session_id: "${sessionId}"\n` +
		`- runtime: ${runtime}\n\n` +
		`Every MCP tool call REQUIRES workspace_id="${workspaceId}". Session-scoped tools ` +
		`ALSO require session_id="${sessionId}". Do NOT call start_session / stop_session — the UI owns lifecycle.\n\n` +
		`## File access (two paths, same S3 folder)\n` +
		`1. MCP file tools (session-less): \`read(workspace_id, file_path)\` / \`write\` / \`delete\` / \`ls\`. Paths are relative to the workspace root: \`read(workspace_id="${workspaceId}", file_path="report.pdf")\`.\n` +
		`2. Sandbox filesystem mount: ${mountLine}\n\n` +
		`## Execution\n` +
		`- Inline code: \`execute_code(workspace_id, session_id, code, language)\` — for python this is a PERSISTENT kernel (imports/vars survive across calls in this session).\n` +
		`- Quick shell: \`execute_command(workspace_id, session_id, command)\`.\n` +
		`- Long-running (installs, big scripts): \`start_command_execution\` → \`wait_task(workspace_id, session_id, task_id, timeout_s=60)\`. wait_task blocks server-side with backoff and returns partial state on timeout — if still running, call wait_task again. NEVER loop \`get_task\` yourself: repeated get_task calls burn per-session InvokeCodeInterpreter quota and fail with ServiceQuotaExceededException. get_task is for a single status peek only.\n\n` +
		`## Runtime environment\n` +
		`Linux container. Python is \`python3\`. Node.js available. Common data / doc libs preinstalled: numpy, pandas, scipy, sklearn, matplotlib, pillow, openpyxl, pypdf, pdfplumber, pymupdf (\`import pymupdf\`), python-docx, python-pptx, requests, boto3. Add more with \`pip install X\`.\n\n` +
		`Be concise. Confirm intent for destructive operations.`
	);
}

export const POST: RequestHandler = async ({ request }) => {
	const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
	const MODEL = process.env.CHAT_MODEL ?? 'claude-haiku-4-5';
	if (!ANTHROPIC_KEY) {
		return new Response(JSON.stringify({ error: 'ANTHROPIC_API_KEY not set on server' }), {
			status: 500,
			headers: { 'Content-Type': 'application/json' }
		});
	}

	const {
		messages,
		workspace_id,
		session_id,
		runtime,
		mount_name
	}: {
		messages: ChatMessage[];
		workspace_id: string;
		session_id: string;
		runtime: string;
		mount_name: string;
	} = await request.json();

	if (!workspace_id || !session_id) {
		return new Response(JSON.stringify({ error: 'workspace_id and session_id required' }), {
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

			const system = buildSystemPrompt({
				workspaceId: workspace_id,
				sessionId: session_id,
				runtime,
				mountName: mount_name ?? ''
			});

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
							send({
								type: 'tool_use',
								tool_use_id: block.id,
								name: block.name,
								input: block.input
							});
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

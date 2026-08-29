# agent-runtime-adapter

Umbrella repo for agent-runtime experiments. Each folder under [`experiments/`](experiments/) is a self-contained project with its own `pyproject.toml` / `package.json` and dependencies.

## Experiments

| Folder | Language | Purpose |
| --- | --- | --- |
| [`experiments/deepagents-repl/`](experiments/deepagents-repl/) | Python | Original agent runtime adapter — deepagents REPL with mirage+bwrap sandbox. |
| [`experiments/vff/`](experiments/vff/) | Python | Virtual filesystem MCP prototype — single-workspace mirage + monty over S3. |
| [`experiments/eks-agent/`](experiments/eks-agent/) | Python | EKS-deployed agent (Bedrock AgentCore stub). |
| [`experiments/agentcore-ada/`](experiments/agentcore-ada/) | AWS CDK + Python | AgentCore infrastructure declarations and agent code. |
| [`experiments/vfs-workspace/`](experiments/vfs-workspace/) | Python + TypeScript | Multi-runtime workspace service + Svelte UI. |

Each experiment has its own `README.md` with run instructions.

## Design docs

- [Spec — vfs-workspace](docs/superpowers/specs/2026-08-29-vfs-workspace-design.md)
- [Plan — vfs-workspace](docs/superpowers/plans/2026-08-29-vfs-workspace.md)

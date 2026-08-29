# agent-runtime-adapter root Makefile.
# Dispatches to experiment-specific targets. Default experiment: vfs-workspace.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

VFS_DIR       := experiments/vfs-workspace
VFS_SERVICE   := $(VFS_DIR)/service
VFS_UI        := $(VFS_DIR)/ui
VFS_IMAGE_DIR := $(VFS_DIR)/runtime-image
VFS_IMAGE_TAG ?= mirage-runtime:latest
VFS_SERVICE_PORT ?= 8100
VFS_UI_PORT ?= 5273
VFS_YAML := $(VFS_SERVICE)/workspaces.yaml

.PHONY: help
help: ## show this help
	@printf 'agent-runtime-adapter — make targets\n\n'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# vfs-workspace targets
# ---------------------------------------------------------------------------

.PHONY: dev
dev: dev-vfs ## default: boot vfs-workspace (service + ui + runtime image)

.PHONY: dev-vfs
dev-vfs: check-aws check-ports vfs-image vfs-config vfs-deps ## boot vfs-workspace (Ctrl-C to stop)
	@printf '\033[32m\n  service:  http://127.0.0.1:$(VFS_SERVICE_PORT)/health\n  ui:       http://127.0.0.1:$(VFS_UI_PORT)\n  ctrl-c to stop\n\n\033[0m'
	@trap 'kill 0' EXIT INT TERM; \
	 ( cd $(VFS_SERVICE) && WORKSPACES_YAML=./workspaces.yaml \
	     uv run uvicorn workspace_service.main:app \
	         --reload --port $(VFS_SERVICE_PORT) --host 127.0.0.1 ) & \
	 ( cd $(VFS_UI) && PUBLIC_API_BASE=http://127.0.0.1:$(VFS_SERVICE_PORT) \
	     pnpm dev --port $(VFS_UI_PORT) ) & \
	 wait

.PHONY: vfs-image
vfs-image: ## build runtime-image (mirage-runtime:latest) if missing
	@if docker image inspect $(VFS_IMAGE_TAG) >/dev/null 2>&1; then \
	    echo "runtime image $(VFS_IMAGE_TAG) already built"; \
	else \
	    echo "building runtime image $(VFS_IMAGE_TAG)"; \
	    docker build -t $(VFS_IMAGE_TAG) $(VFS_IMAGE_DIR); \
	fi

.PHONY: vfs-image-rebuild
vfs-image-rebuild: ## force rebuild of runtime-image
	docker build --no-cache -t $(VFS_IMAGE_TAG) $(VFS_IMAGE_DIR)

.PHONY: vfs-config
vfs-config: ## seed service/workspaces.yaml from example if missing
	@if [ ! -f $(VFS_YAML) ]; then \
	    echo "creating $(VFS_YAML) from example — edit it with your S3 bucket/prefix"; \
	    cp $(VFS_DIR)/workspaces.yaml.example $(VFS_YAML); \
	fi

.PHONY: vfs-deps
vfs-deps: ## uv sync + pnpm install
	@echo "uv sync ($(VFS_SERVICE))"
	@cd $(VFS_SERVICE) && uv sync
	@if [ ! -d $(VFS_UI)/node_modules ]; then \
	    echo "pnpm install ($(VFS_UI))"; \
	    cd $(VFS_UI) && pnpm install; \
	fi

.PHONY: vfs-service
vfs-service: check-aws check-service-port vfs-config vfs-deps ## run just the service
	@cd $(VFS_SERVICE) && WORKSPACES_YAML=./workspaces.yaml \
	    uv run uvicorn workspace_service.main:app --reload --port $(VFS_SERVICE_PORT) --host 127.0.0.1

.PHONY: vfs-ui
vfs-ui: check-ui-port vfs-deps ## run just the ui
	@cd $(VFS_UI) && PUBLIC_API_BASE=http://127.0.0.1:$(VFS_SERVICE_PORT) \
	    pnpm dev --port $(VFS_UI_PORT)

.PHONY: vfs-test
vfs-test: ## run vfs-workspace service tests
	@cd $(VFS_SERVICE) && uv run pytest -v

.PHONY: vfs-clean
vfs-clean: ## kill stray mirage-runtime containers
	@docker ps -a --filter 'name=mirage-ws-' --format '{{.ID}}' | xargs -r docker rm -f

# ---------------------------------------------------------------------------
# prereq checks
# ---------------------------------------------------------------------------

.PHONY: check-aws
check-aws:
	@if [ -z "$${AWS_ACCESS_KEY_ID:-}" ] && [ -z "$${AWS_PROFILE:-}" ] && [ ! -f "$$HOME/.aws/credentials" ]; then \
	    printf '\033[31mAWS creds not found: set AWS_PROFILE / AWS_ACCESS_KEY_ID / SECRET / REGION, or run `aws configure`\033[0m\n' >&2; \
	    exit 1; \
	fi
	@printf '\033[36maws: %s region=%s\033[0m\n' "$${AWS_PROFILE:-$$( [ -f $$HOME/.aws/credentials ] && echo '~/.aws' || echo '<explicit keys>')}" "$${AWS_REGION:-$${AWS_DEFAULT_REGION:-$$(aws configure get region 2>/dev/null || echo unset)}}"

.PHONY: check-ports
check-ports: check-service-port check-ui-port

.PHONY: check-service-port
check-service-port:
	@if lsof -iTCP:$(VFS_SERVICE_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    printf '\033[31mservice port $(VFS_SERVICE_PORT) already in use — set VFS_SERVICE_PORT=<port> to override\033[0m\n' >&2; \
	    exit 1; \
	fi

.PHONY: check-ui-port
check-ui-port:
	@if lsof -iTCP:$(VFS_UI_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    printf '\033[31mui port $(VFS_UI_PORT) already in use — set VFS_UI_PORT=<port> to override\033[0m\n' >&2; \
	    exit 1; \
	fi

.PHONY: check-prereqs
check-prereqs: ## verify docker/uv/pnpm on PATH and docker daemon up
	@for bin in docker uv pnpm; do command -v $$bin >/dev/null || { echo "missing: $$bin" >&2; exit 1; }; done
	@docker info >/dev/null 2>&1 || { echo "docker daemon not running" >&2; exit 1; }
	@echo "prereqs ok"

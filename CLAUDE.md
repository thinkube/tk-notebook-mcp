# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

tk-ai-extension is a JupyterLab extension that provides Claude AI capabilities for Jupyter notebooks. It includes:
- A chat sidebar UI ("Thinky") for interacting with Claude
- MCP (Model Context Protocol) tools for notebook operations
- Real-time collaboration via YDoc/CRDT for instant cell updates
- Conversation persistence stored in notebook metadata

## Build Commands

```bash
# Install dependencies
jlpm install                      # Frontend (TypeScript/React)
pip install -e ".[dev]"          # Backend (Python)

# Development build (with source maps)
jlpm build

# Production build
jlpm build:prod

# Watch mode (auto-rebuild on changes)
jlpm watch

# Lint and format
jlpm lint                         # Run all linters
jlpm eslint                       # Fix ESLint issues
jlpm prettier                     # Format code
jlpm stylelint                    # Fix CSS issues

# Clean builds
jlpm clean                        # Clean lib directory
jlpm clean:all                    # Clean everything
```

## Testing

```bash
# Python tests
pytest                                    # Run all tests
pytest tests/test_tools.py               # Single test file
pytest --cov=tk_ai_extension             # With coverage

# TypeScript tests
jlpm test                                # Jest tests with coverage

# UI tests (Playwright)
cd ui-tests && npm install && npm test
```

## Architecture

### Two-Part Extension

**Frontend (TypeScript/React)** - `src/`
- `index.ts` - JupyterLab plugin entry point, registers toolbar button and commands
- `widget.tsx` - ChatWidget using Lumino ReactWidget
- `components/ChatPanel.tsx` - Main chat UI component
- `api.ts` - MCPClient class for backend communication

**Backend (Python)** - `tk_ai_extension/`
- `extension.py` - Server extension entry, registers HTTP handlers
- `handlers.py` - Tornado HTTP handlers for MCP endpoints
- `agent/tools_registry.py` - Tool registration with Claude Agent SDK
- `mcp/tools/` - Individual MCP tool implementations
- `conversation_persistence.py` - Save/load conversations via YDoc

### Request Flow

```
ChatPanel -> MCPClient -> /api/tk-ai/mcp/chat -> MCPChatHandler
    -> ClaudeSDKClient -> MCP Server -> tool_executor -> BaseTool.execute()
```

### Key Managers (Backend)

Tools receive Jupyter managers via `_jupyter_managers` global in `tools_registry.py`:
- `contents_manager` - File operations
- `kernel_manager` - Kernel lifecycle
- `session_manager` - Kernel-notebook sessions
- `notebook_manager` - Active notebook tracking
- `serverapp` - Access to ExecutionStack (jupyter-server-nbmodel)

### MCP Tool Structure

All tools extend `BaseTool` in `tk_ai_extension/mcp/tools/base.py`:
```python
async def execute(self, contents_manager, kernel_manager, ..., **kwargs) -> Any
```

Tool categories:
- `mcp/tools/` - Notebook operations (list_cells, read_cell, create_notebook)
- `mcp/tools/kernel/` - Kernel management (restart, interrupt, status)
- `mcp/tools/execution/` - Code execution (execute_cell, execute_ipython)
- `mcp/tools/introspection/` - Python environment (list_modules, check_module)

### Real-Time Collaboration

Cell modifications use YDoc (CRDT) for instant UI updates without page refresh:
- `overwrite_cell` tool modifies cells via YDoc
- Conversation history stored in notebook metadata via YDoc
- `document_id` set in sharedModel for RTC execution support

## API Endpoints

- `GET /api/tk-ai/mcp/health` - Health check
- `GET /api/tk-ai/mcp/model-health` - Claude API key status
- `GET /api/tk-ai/mcp/tools/list` - List available tools
- `POST /api/tk-ai/mcp/tools/call` - Execute a tool directly
- `POST /api/tk-ai/mcp/chat` - Send message to Claude (uses MCP tools)
- `POST /api/tk-ai/mcp/notebook/connect` - Connect to notebook, load history
- `POST /api/tk-ai/mcp/session/close` - Close Claude session
- `POST /api/tk-ai/mcp/conversation/clear` - Clear conversation history
- `GET /api/tk-ai/fileid` - Get document_id UUID for RTC

## Configuration

API credentials loaded from `~/thinkube/notebooks/.secrets.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-...
# or
CLAUDE_CODE_OAUTH_TOKEN=...
```

Extension settings in `schema/plugin.json`.

## Code Style

- **TypeScript**: Single quotes, no trailing commas, arrow functions preferred
- **Python**: black + ruff for formatting/linting
- **Interfaces**: Must start with `I` prefix (e.g., `ITool`, `IChatMessage`)
- **ESLint rules**: Strict curly braces, strict equality

## Key Dependencies

- `claude-agent-sdk` - Claude AI integration with MCP support
- `jupyter-server-nbmodel` - Non-blocking execution via ExecutionStack
- `@jupyterlab/*` 4.x - JupyterLab core packages
- `marked` - Markdown rendering in chat

@../../core/thinkube-metadata/plugins/tandem-methodology/methodology.md

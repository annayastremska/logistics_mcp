#!/bin/sh
# Manual MCP handshake over stdio, for the defence: no agent, no Inspector,
# just three JSON-RPC messages typed by a human straight into the server's stdin.
#
#   bash scripts/manual_stdio_demo.sh

printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual-test","version":"1.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| .venv/Scripts/python -m mcp_server.server 2>/dev/null \
| tail -n 1 \
| python -m json.tool

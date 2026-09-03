#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
# Cursor MCP 不會自動注入 .env；啟動前先匯出 GROQ_API_KEY 等變數
if [ -f "$DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DIR/.env"
  set +a
fi
source "$DIR/.venv/bin/activate"
exec python "$DIR/mcp_server.py"

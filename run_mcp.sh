#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
source "$DIR/.venv/bin/activate"
exec python "$DIR/mcp_server.py"

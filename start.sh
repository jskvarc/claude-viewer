#!/usr/bin/env bash
# Start Claude Code Viewer in the background.
# Usage: ./start.sh [--port N] [--host ADDR]
# On exit, the port and process ID are printed and written to claude-viewer.run.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PORT=8092
HOST=0.0.0.0

while [[ $# -gt 0 ]]; do
    case $1 in
        --port) PORT=$2; shift 2 ;;
        --host) HOST=$2; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--port N] [--host ADDR]"
            echo "Defaults: --port 8092 --host 0.0.0.0"
            exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done

PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x $PYTHON ]]; then
    echo "No virtualenv found. Set it up first:" >&2
    echo "  python3 -m venv $SCRIPT_DIR/.venv && $SCRIPT_DIR/.venv/bin/pip install -r $SCRIPT_DIR/requirements.txt" >&2
    exit 1
fi

LOG_FILE="$SCRIPT_DIR/claude-viewer.log"
RUN_FILE="$SCRIPT_DIR/claude-viewer.run"

# Refuse to start a second instance recorded in the run file.
if [[ -f $RUN_FILE ]]; then
    OLD_PID=$(sed -n 's/^pid=//p' "$RUN_FILE")
    if [[ -n $OLD_PID ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running (pid $OLD_PID). Stop it with: kill $OLD_PID" >&2
        exit 1
    fi
fi

nohup "$PYTHON" "$SCRIPT_DIR/main.py" --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
PID=$!

# Wait up to 15 s for the server to answer before declaring success.
STARTED=0
for _ in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:$PORT/"; then
        STARTED=1
        break
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Server exited during startup — last log lines ($LOG_FILE):" >&2
        tail -n 5 "$LOG_FILE" >&2
        exit 1
    fi
    sleep 0.5
done

if [[ $STARTED -ne 1 ]]; then
    echo "Server (pid $PID) did not answer on port $PORT within 15 s — check $LOG_FILE" >&2
    kill "$PID" 2>/dev/null || true
    exit 1
fi

printf 'port=%s\npid=%s\n' "$PORT" "$PID" | tee "$RUN_FILE"
echo "Claude Code Viewer running at http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT (log: $LOG_FILE)"

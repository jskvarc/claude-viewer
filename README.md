# Claude Code Viewer

A NiceGUI web app for browsing and searching your Claude Code session history
(`~/.claude/projects`).

## Features

- **Project browser** — lists every Claude Code project, its sessions, and the
  full conversation (your prompts and Claude's responses, with an optional
  "show tool calls" view).
- **Text search** — instant substring search across all projects or the
  selected one, with highlighted matches.
- **Semantic search** — embeds every prompt/response through any
  OpenAI-compatible embeddings endpoint (e.g. Ollama on another machine) and
  ranks results by cosine similarity. Embeddings are cached in
  `~/.cache/claude-viewer/embeddings/` and refreshed automatically when a
  session file or the model changes.
- **LLM server configuration in the GUI** — gear icon, top right: base URL,
  API key, embedding model, result count, plus a connection test. Settings
  persist in `~/.config/claude-viewer/config.json`.

## Install & run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
./start.sh                          # background server on 0.0.0.0:8092
./start.sh --port 9000              # custom port
```

`start.sh` starts the server in the background, waits until it answers, and
writes the port and process ID to `claude-viewer.run` (also printed to the
terminal). Logs go to `claude-viewer.log`. It refuses to start twice; stop
the server with:

```bash
kill $(sed -n 's/^pid=//p' claude-viewer.run)
```

To run in the foreground instead:

```bash
.venv/bin/python main.py            # http://127.0.0.1:8080
.venv/bin/python main.py --show     # also opens the browser
.venv/bin/python main.py --host 0.0.0.0 --port 9000
```

## Using Ollama as the LLM server

On the machine that hosts Ollama (local or remote):

```bash
ollama pull nomic-embed-text
# to accept connections from other machines:
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then in the app settings (gear icon):

| Field | Value |
|---|---|
| Base URL | `http://<server-ip>:11434/v1` |
| API key | anything (Ollama ignores it) |
| Embedding model | `nomic-embed-text` |

Any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp,
OpenAI itself) works the same way — point the base URL at its `/v1` root.

## Semantic search workflow

1. Open the **Search** tab and switch the toggle to **Semantic**.
2. Click **Build index** once (progress bar shows per-session progress).
   Only new or changed sessions are re-embedded on later runs.
3. Type a query and press Enter. Results are ranked by similarity;
   clicking one opens the conversation scrolled to the matching message.

## License

MIT — see [LICENSE](LICENSE).

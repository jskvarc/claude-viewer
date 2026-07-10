"""Persistent settings for the LLM server (OpenAI-compatible API)."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = Path.home() / '.config' / 'claude-viewer' / 'config.json'

DEFAULTS = {
    'base_url': 'http://127.0.0.1:11434/v1',
    'api_key': 'ollama',
    'embedding_model': 'nomic-embed-text',
    'top_k': 10,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return cfg
    cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({k: cfg[k] for k in DEFAULTS}, indent=2), encoding='utf-8')

"""Text and semantic search over parsed sessions.

Semantic search embeds every prompt/response through an OpenAI-compatible
``/v1/embeddings`` endpoint (e.g. Ollama) and ranks by cosine similarity.
Vectors are cached on disk per session file, keyed by file mtime and model.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from . import store

CACHE_DIR = Path.home() / '.cache' / 'claude-viewer' / 'embeddings'
EMBED_BATCH = 16
MAX_EMBED_CHARS = 4000
PREVIEW_CHARS = 400


@dataclass
class Hit:
    project: store.Project
    session_path: Path
    session_title: str
    uuid: str
    role: str
    preview: str
    score: float | None = None  # cosine similarity; None for text hits
    span: tuple[int, int] | None = None  # match position within preview


def scope_pairs(projects: list[store.Project],
                only: store.Project | None = None) -> list[tuple[store.Project, Path]]:
    pairs = []
    for project in projects:
        if only is not None and project is not only:
            continue
        pairs.extend((project, f) for f in project.session_files)
    return pairs


def text_search(pairs: list[tuple[store.Project, Path]], query: str, limit: int = 200) -> list[Hit]:
    needle = query.lower()
    hits: list[Hit] = []
    for project, path in pairs:
        data = store.load_session(path)
        for message in data.messages:
            if message.role == 'tool':
                continue
            pos = message.text.lower().find(needle)
            if pos < 0:
                continue
            start = max(0, pos - 90)
            end = min(len(message.text), pos + len(needle) + 90)
            hits.append(Hit(project, path, data.title, message.uuid, message.role,
                            message.text[start:end], span=(pos - start, pos - start + len(needle))))
            if len(hits) >= limit:
                return hits
    return hits


def make_client(cfg: dict, timeout: float = 60.0) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=cfg['base_url'], api_key=cfg['api_key'] or 'none', timeout=timeout)


async def test_connection(cfg: dict) -> str:
    client = make_client(cfg, timeout=10.0)
    models = await client.models.list()
    names = [m.id for m in models.data]
    note = '' if cfg['embedding_model'] in names else f' — warning: "{cfg["embedding_model"]}" not in the list'
    return f'OK, {len(names)} model(s) available{note}'


class SemanticIndex:
    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self.cache_dir = cache_dir
        self._mem: dict[str, tuple[float, dict, np.ndarray]] = {}

    def _key(self, path: Path, model: str) -> str:
        return hashlib.sha1(f'{path}|{model}'.encode()).hexdigest()

    def _load(self, path: Path, model: str) -> tuple[dict, np.ndarray] | None:
        key = self._key(path, model)
        mtime = path.stat().st_mtime
        cached = self._mem.get(key)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        meta_file = self.cache_dir / f'{key}.json'
        vec_file = self.cache_dir / f'{key}.npy'
        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        if meta.get('mtime') != mtime or not vec_file.exists():
            return None
        vectors = np.load(vec_file)
        self._mem[key] = (mtime, meta, vectors)
        return meta, vectors

    def status(self, pairs: list[tuple[store.Project, Path]], model: str) -> tuple[int, int]:
        indexed = sum(1 for _, path in pairs if self._load(path, model) is not None)
        return indexed, len(pairs)

    async def build(self, pairs: list[tuple[store.Project, Path]], cfg: dict,
                    progress=None) -> int:
        """Embed all un-indexed sessions; returns how many were (re)built."""
        client = make_client(cfg, timeout=300.0)
        model = cfg['embedding_model']
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        built = 0
        for done, (_, path) in enumerate(pairs):
            if progress:
                progress(done, len(pairs), path.name)
            if self._load(path, model) is not None:
                continue
            mtime = path.stat().st_mtime
            data = store.load_session(path)
            docs = [m for m in data.messages if m.role != 'tool' and len(m.text) >= 8]
            embeddings: list[list[float]] = []
            for start in range(0, len(docs), EMBED_BATCH):
                batch = [m.text[:MAX_EMBED_CHARS] for m in docs[start:start + EMBED_BATCH]]
                response = await client.embeddings.create(model=model, input=batch)
                embeddings.extend(item.embedding for item in response.data)
            vectors = np.array(embeddings, dtype=np.float32) if embeddings else np.zeros((0, 1), np.float32)
            if len(vectors):
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                vectors /= norms
            key = self._key(path, model)
            np.save(self.cache_dir / f'{key}.npy', vectors)
            meta = {
                'session_path': str(path), 'mtime': mtime, 'model': model, 'title': data.title,
                'docs': [{'uuid': m.uuid, 'role': m.role, 'preview': m.text[:PREVIEW_CHARS]} for m in docs],
            }
            (self.cache_dir / f'{key}.json').write_text(json.dumps(meta), encoding='utf-8')
            self._mem[key] = (mtime, meta, vectors)
            built += 1
        if progress:
            progress(len(pairs), len(pairs), 'done')
        return built

    async def search(self, pairs: list[tuple[store.Project, Path]], cfg: dict, query: str,
                     top_k: int = 10) -> tuple[list[Hit], int]:
        """Returns (hits, number of sessions missing from the index)."""
        client = make_client(cfg)
        model = cfg['embedding_model']
        response = await client.embeddings.create(model=model, input=[query[:MAX_EMBED_CHARS]])
        query_vec = np.array(response.data[0].embedding, dtype=np.float32)
        norm = np.linalg.norm(query_vec)
        if norm:
            query_vec /= norm
        hits: list[Hit] = []
        missing = 0
        for project, path in pairs:
            loaded = self._load(path, model)
            if loaded is None:
                missing += 1
                continue
            meta, vectors = loaded
            if not len(vectors):
                continue
            if vectors.shape[1] != query_vec.shape[0]:
                missing += 1  # embedded with a different model; needs rebuild
                continue
            scores = vectors @ query_vec
            for idx in np.argsort(scores)[::-1][:top_k]:
                doc = meta['docs'][int(idx)]
                hits.append(Hit(project, path, meta.get('title') or path.stem,
                                doc['uuid'], doc['role'], doc['preview'], score=float(scores[idx])))
        hits.sort(key=lambda h: h.score or 0.0, reverse=True)
        return hits[:top_k], missing

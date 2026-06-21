#!/usr/bin/env python3
"""
vector_store.py — Gemini Embedding 向量检索层

功能：
- 使用 Google gemini-embedding-2 生成文本向量（3072 维）
- 存储向量到 SQLite BLOB（独立 ars_vectors 表，不依赖 vec0 扩展）
- 余弦相似度检索（朴素 O(n) 实现，适用于小到中等规模；大规模建议
  外置 pgvector / faiss）

可选 DoH（DNS over HTTPS）兜底：当本机 DNS 被透明代理劫持时,可设
``AGENTMESH_RUNTIME_DOH_BYPASS=1`` 走 Google DoH 解析 generativelanguage
*.googleapis.com 的真实 IP。默认关闭。

用法：
    from vector_store import VectorStore
    vs = VectorStore(sqlite_path="/path/to/vectors.db")
    vs.embed("hello world")  # 返回 3072 维向量 list[float]
    vs.store("session_123", "hello world")  # 存向量
    hits = vs.search("hello", top_k=5)  # 搜索
"""

from __future__ import annotations
import json
from datetime import datetime
import os
import sqlite3
import struct
import subprocess
import time
from pathlib import Path
from typing import Optional

# ==================== DNS Bypass (DoH) ====================

_DNS_CACHE: dict = {}
_HIJACK_DOMAINS = (
    "googleapis.com",
    "generativelanguage.googleapis.com",
)


def _resolve_real_ip(hostname: str) -> Optional[str]:
    """Optional DoH fallback. Disabled unless ``AGENTMESH_RUNTIME_DOH_BYPASS=1``.

    When enabled, resolves real IPs for known Google API hostnames via
    ``https://dns.google/resolve`` to bypass transparent-proxy DNS hijack.
    Filters out CGNAT-style fake responses in the 198.18.0.0/15 range.
    """
    if os.getenv("AGENTMESH_RUNTIME_DOH_BYPASS", "0") not in ("1", "true", "True"):
        return None

    if hostname in _DNS_CACHE:
        return _DNS_CACHE[hostname]

    needs_bypass = any(hostname.endswith(d) for d in _HIJACK_DOMAINS)
    if not needs_bypass:
        return None

    try:
        r = subprocess.run(
            ["curl", "-s", f"https://dns.google/resolve?name={hostname}&type=A"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(r.stdout)
        for answer in data.get("Answer", []):
            ip = answer["data"]
            # Drop CGNAT / fake-IP ranges that proxies sometimes return.
            if not ip.startswith("198.18."):
                _DNS_CACHE[hostname] = ip
                return ip
    except Exception:
        pass
    return None


# ==================== Vector Store ====================

class VectorStore:
    """SQLite-backed Gemini embedding vector store."""

    DIM = 3072  # gemini-embedding-2 输出 3072 维
    MODEL = "gemini-embedding-2"

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else Path.home() / ".openclaw" / "memory" / "ars_vectors.db"
        self._init_db()

    def _init_db(self):
        """初始化 ars_vectors 表。"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ars_vectors (
                id       TEXT PRIMARY KEY,     -- session_id 或 chunk_id
                text     TEXT NOT NULL,       -- 原始文本（用于展示）
                text_hash TEXT NOT NULL,        -- SHA256(text) 用于去重
                vector   BLOB NOT NULL,        -- float32[3072] 大端序
                source   TEXT DEFAULT 'ars',   -- 来源标记
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ars_vectors_hash ON ars_vectors(text_hash)")
        conn.commit()
        conn.close()

    # ── Embedding API ────────────────────────────────────────────────

    def _get_api_key(self) -> str | None:
        """从环境变量获取 Gemini API key。"""
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def embed(self, text: str) -> list[float] | None:
        """调用 Gemini embedding-2 API，返回 3072 维向量。失败返回 None。"""
        key = self._get_api_key()
        if not key:
            return None

        hostname = "generativelanguage.googleapis.com"
        real_ip = _resolve_real_ip(hostname)
        url = f"https://{hostname}/v1beta/models/gemini-embedding-2:embedContent?key={key}"

        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", "Content-Type: application/json",
            "--max-time", "20",
        ]
        if real_ip:
            cmd += ["--resolve", f"{hostname}:443:{real_ip}"]

        body = json.dumps({
            "model": "models/gemini-embedding-2",
            "content": {"parts": [{"text": text[:8192]}]}  # 截断防超限
        })
        cmd += ["-d", body]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return None
            data = json.loads(r.stdout)
            vals = data.get("embedding", {}).get("values")
            if vals and len(vals) == self.DIM:
                return vals
        except Exception:
            pass
        return None

    # ── Storage ───────────────────────────────────────────────────

    def store(self, doc_id: str, text: str, source: str = "ars") -> bool:
        """生成向量并存储。doc_id 唯一，重复调用更新。返回 True/False。"""
        vec = self.embed(text)
        if vec is None:
            return False

        import hashlib, struct as _struct
        vec_bytes = _struct.pack(f">{len(vec)}f", *vec)
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        now = datetime.now().isoformat()

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            INSERT OR REPLACE INTO ars_vectors (id, text, text_hash, vector, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (doc_id, text[:10000], text_hash, vec_bytes, source, now))
        conn.commit()
        conn.close()
        return True

    def store_batch(self, docs: list[dict]) -> int:
        """
        批量存储 docs = [{"id": str, "text": str, "source": str}]
        返回成功存储的数量。
        """
        import hashlib, struct as _struct
        conn = sqlite3.connect(str(self.db_path))
        stored = 0
        for doc in docs:
            vec = self.embed(doc["text"])
            if vec is None:
                continue
            vec_bytes = _struct.pack(f">{len(vec)}f", *vec)
            text_hash = hashlib.sha256(doc["text"].encode()).hexdigest()
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT OR REPLACE INTO ars_vectors (id, text, text_hash, vector, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (doc["id"], doc["text"][:10000], text_hash, vec_bytes, doc.get("source","ars"), now))
            stored += 1
        conn.commit()
        conn.close()
        return stored

    # ── Search ─────────────────────────────────────────────────────

    @staticmethod
    def _cosine(a: bytes, b: bytes) -> float:
        """从 BLOB 计算两个向量的余弦相似度。"""
        import struct as _struct
        va = _struct.unpack(f">{VectorStore.DIM}f", a)
        vb = _struct.unpack(f">{VectorStore.DIM}f", b)
        dot = sum(x * y for x, y in zip(va, vb))
        norm_a = sum(x * x for x in va) ** 0.5
        norm_b = sum(x * x for x in vb) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    def search(self, query: str, top_k: int = 5, min_score: float = 0.5) -> list[dict]:
        """
        向量相似度搜索。
        返回 [{"id", "text", "score", "source"}, ...]，按 score 降序。
        """
        q_vec = self.embed(query)
        if q_vec is None:
            return []

        import struct as _struct
        q_bytes = _struct.pack(f">{len(q_vec)}f", *q_vec)

        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT id, text, vector, source FROM ars_vectors"
        ).fetchall()
        conn.close()

        hits = []
        for row_id, text, vec_bytes, source in rows:
            if not vec_bytes:
                continue
            score = self._cosine(q_bytes, vec_bytes)
            if score >= min_score:
                hits.append({
                    "id": row_id,
                    "text": text[:500],
                    "score": round(score, 4),
                    "source": source or "ars",
                })

        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:top_k]

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        """返回向量库统计。"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT COUNT(*), COUNT(DISTINCT source) FROM ars_vectors")
        count, source_count = cursor.fetchone()
        conn.close()
        return {"total_vectors": count, "unique_sources": source_count, "dim": self.DIM}


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ARS Vector Store CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_embed = sub.add_parser("embed")
    p_embed.add_argument("text", help="要嵌入的文本")

    p_store = sub.add_parser("store")
    p_store.add_argument("id", help="文档 ID")
    p_store.add_argument("text", help="要存储的文本")

    p_search = sub.add_parser("search")
    p_search.add_argument("query", help="搜索查询")
    p_search.add_argument("--top-k", type=int, default=5)
    p_search.add_argument("--min-score", type=float, default=0.5)

    p_stats = sub.add_parser("stats")

    args = parser.parse_args()
    vs = VectorStore()

    if args.cmd == "embed":
        vec = vs.embed(args.text)
        if vec:
            print(f"OK: dim={len(vec)}, first5={vec[:5]}")
        else:
            print("FAILED: embedding API 不可用（检查 GEMINI_API_KEY 或网络）")

    elif args.cmd == "store":
        ok = vs.store(args.id, args.text)
        print("OK" if ok else "FAILED")

    elif args.cmd == "search":
        hits = vs.search(args.query, args.top_k, args.min_score)
        for h in hits:
            print(f"  score={h['score']:.4f} id={h['id']} text={h['text'][:60]}...")

    elif args.cmd == "stats":
        s = vs.stats()
        print(f"Vectors: {s['total_vectors']}, Sources: {s['unique_sources']}, Dim: {s['dim']}")

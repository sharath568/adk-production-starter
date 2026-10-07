"""Knowledge tool: answers from internal docs.

Two backends, same tool signature:
- RAG_API_URL set  -> calls the vertex-alloydb-rag service on Cloud Run (hybrid search on AlloyDB,
                      grounded answer with citations), authenticated with a Google ID token.
- RAG_API_URL unset -> a tiny local keyword index over data/docs, so the agent runs offline.

The tenant is read from session state, which the server sets from the authenticated user.
The model never gets to choose it. That's the difference between a filter and a suggestion.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import httpx
from google.adk.tools import ToolContext

from .. import config

DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "docs"
_WORD = re.compile(r"[a-z0-9_]+")
_STOP = {"the", "a", "an", "is", "are", "do", "does", "i", "we", "how", "what", "to", "of", "in", "on", "for", "and", "can", "my", "our"}


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


@lru_cache(maxsize=1)
def _local_index() -> list[dict]:
    """Split each doc into sections by '## ' headings."""
    passages = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        text = re.sub(r"^---\n.*?\n---\n", "", f.read_text(), flags=re.S)
        for block in re.split(r"\n(?=## )", text):
            heading = block.splitlines()[0].lstrip("# ").strip() if block.strip() else ""
            passages.append({"source": f"{f.name}#{heading}", "text": block.strip(), "terms": _terms(block)})
    return passages


def _local_search(question: str, k: int = 3) -> dict:
    q = _terms(question)
    scored = sorted(
        ((len(q & p["terms"]) / (len(q) or 1), p) for p in _local_index()),
        key=lambda x: x[0],
        reverse=True,
    )
    hits = [{"source": p["source"], "text": p["text"][:1200], "score": round(s, 2)} for s, p in scored[:k] if s > 0]
    return {"backend": "local", "grounded": bool(hits), "answer": None, "passages": hits}


def _id_token(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token

    return google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)


def _remote_ask(question: str, tenant: str) -> dict:
    url = config.RAG_API_URL.rstrip("/")
    resp = httpx.post(
        f"{url}/ask",
        json={"question": question},
        headers={"Authorization": f"Bearer {_id_token(url)}", "X-Tenant-Id": tenant},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    return {"backend": "rag-service", "grounded": body["grounded"], "answer": body["answer"],
            "passages": body.get("sources", [])}


def search_docs(question: str, tool_context: ToolContext) -> dict:
    """Search the team's internal runbooks and docs.

    Use this for any question about how things are done here: backups, restores, deploys,
    rollbacks, incident severity, error codes, credential rotation.

    Args:
        question: The user's question, rewritten to be self-contained.

    Returns:
        grounded: whether relevant docs were found. If false, tell the user you don't know.
        answer: a cited answer (rag-service backend) or null (local backend).
        passages: the supporting doc sections.
    """
    tenant = tool_context.state.get("tenant", "default")
    try:
        if config.RAG_API_URL:
            return _remote_ask(question, tenant)
        return _local_search(question)
    except httpx.HTTPError as e:
        # Return the failure as data. The agent can tell the user; an exception would end the turn.
        return {"backend": "rag-service", "grounded": False, "answer": None, "passages": [],
                "error": f"knowledge service unavailable: {type(e).__name__}"}

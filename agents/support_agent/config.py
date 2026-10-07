"""Settings from the environment. Same image locally, in CI and on Cloud Run."""

from __future__ import annotations

import os

# Cheap, fast model for routing; stronger model for the specialists that use tools.
# Check what your project can see: python -c "from google import genai; [print(m.name) for m in genai.Client().models.list()]"
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemini-3.5-flash-lite")
SPECIALIST_MODEL = os.getenv("SPECIALIST_MODEL", "gemini-3.5-flash")

# Where the knowledge agent searches. If unset, it uses a small local keyword index over data/docs.
# Point it at the vertex-alloydb-rag service to get hybrid search on AlloyDB.
RAG_API_URL = os.getenv("RAG_API_URL", "")

# Services the ops agent is allowed to touch. Anything else is rejected before the tool runs.
ALLOWED_SERVICES = {
    s.strip() for s in os.getenv("ALLOWED_SERVICES", "orders-api,payments-api,inventory-api").split(",") if s.strip()
}

# Hard ceiling on tool calls per user turn. Stops a confused agent from looping on a tool.
MAX_TOOL_CALLS_PER_TURN = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "6"))

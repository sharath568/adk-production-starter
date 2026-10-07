"""HTTP entry point for Cloud Run, using ADK's FastAPI app.

Endpoints come from ADK: POST /apps/support_agent/users/{user}/sessions to create a session,
POST /run or /run_sse to send a message. Sessions are stored in Postgres (AlloyDB or Cloud SQL)
through SESSION_DB_URL, so any instance can pick up any conversation.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from google.adk.cli.fast_api import get_fast_api_app

AGENTS_DIR = str(Path(__file__).resolve().parent / "agents")

app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    # Local default is a SQLite file; on Cloud Run use postgresql+asyncpg://... from Secret Manager.
    session_service_uri=os.getenv("SESSION_DB_URL", "sqlite+aiosqlite:///./sessions.db"),
    web=os.getenv("ADK_WEB", "false").lower() == "true",  # dev UI off in production
    allow_origins=[o for o in os.getenv("ALLOW_ORIGINS", "").split(",") if o],
    trace_to_cloud=os.getenv("TRACE_TO_CLOUD", "false").lower() == "true",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

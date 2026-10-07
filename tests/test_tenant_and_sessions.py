import pytest

from conftest import call, say, tool_results


@pytest.mark.asyncio
async def test_tenant_comes_from_session_state_not_the_model(harness, monkeypatch):
    from support_agent import config
    from support_agent.tools import knowledge

    sent = {}

    class Resp:
        def raise_for_status(self): ...
        def json(self):
            return {"grounded": True, "answer": "Use update-traffic [1]", "sources": [{"n": 1}]}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, headers=headers, json=json)
        return Resp()

    monkeypatch.setattr(config, "RAG_API_URL", "https://rag.example.run.app")
    monkeypatch.setattr(knowledge, "_id_token", lambda aud: "test-token")
    monkeypatch.setattr(knowledge.httpx, "post", fake_post)

    h = harness([
        call("transfer_to_agent", agent_name="knowledge_agent"),
        # Even if the model tried to pass a tenant, the tool signature has no such parameter.
        call("search_docs", question="how do I roll back?"),
        say("..."),
    ], state={"tenant": "harbor"})
    events = await h.send("how do I roll back?")

    assert sent["headers"]["X-Tenant-Id"] == "harbor"
    assert sent["headers"]["Authorization"] == "Bearer test-token"
    assert tool_results(events, "search_docs")[0]["backend"] == "rag-service"


@pytest.mark.asyncio
async def test_rag_outage_is_returned_as_data(harness, monkeypatch):
    import httpx
    from support_agent import config
    from support_agent.tools import knowledge

    def boom(*a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(config, "RAG_API_URL", "https://rag.example.run.app")
    monkeypatch.setattr(knowledge, "_id_token", lambda aud: "t")
    monkeypatch.setattr(knowledge.httpx, "post", boom)
    h = harness([call("transfer_to_agent", agent_name="knowledge_agent"),
                 call("search_docs", question="x"), say("The docs service is down right now.")])
    events = await h.send("x")
    assert "unavailable" in tool_results(events, "search_docs")[0]["error"]


@pytest.mark.asyncio
async def test_sessions_survive_a_restart_with_database_session_service(tmp_path):
    """Cloud Run instances come and go. Conversation state has to live in a database."""
    from google.adk.runners import Runner
    from google.adk.sessions import DatabaseSessionService
    from google.genai import types
    from support_agent.agent import build_app, build_root_agent
    from conftest import ScriptedLlm

    url = f"sqlite+aiosqlite:///{tmp_path}/sessions.db"
    llm = ScriptedLlm(model="scripted", requests=[], script=[
        call("transfer_to_agent", agent_name="ops_agent"),
        call("get_service_status", service="payments-api"),
        say("payments-api is healthy."),
    ])
    app = build_app(build_root_agent(llm, llm))
    svc = DatabaseSessionService(db_url=url)
    s = await svc.create_session(app_name=app.name, user_id="u1", state={"tenant": "default"})
    msg = types.Content(role="user", parts=[types.Part(text="payments ok?")])
    async for _ in Runner(app=app, session_service=svc).run_async(user_id="u1", session_id=s.id, new_message=msg):
        pass

    # "Restart": a brand-new service object reading the same database.
    reloaded = await DatabaseSessionService(db_url=url).get_session(app_name=app.name, user_id="u1", session_id=s.id)
    texts = [p.text for e in reloaded.events if e.content for p in e.content.parts if p.text]
    assert texts[-1] == "payments-api is healthy."
    assert reloaded.state["tenant"] == "default"

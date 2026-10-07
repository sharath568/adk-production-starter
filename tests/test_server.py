def test_server_lists_the_agent_app(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/s.db")
    import importlib

    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        assert "support_agent" in client.get("/list-apps").json()
        r = client.post("/apps/support_agent/users/u1/sessions", json={"state": {"tenant": "harbor"}})
        assert r.status_code == 200 and r.json()["state"]["tenant"] == "harbor"

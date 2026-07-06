from fastapi.testclient import TestClient

from madosho_server import api, db


def _setup(tmp_path, monkeypatch):
    import procrastinate
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vm.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    from madosho_server import tasks
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    api.app.dependency_overrides[api.get_enqueue] = lambda: (lambda s, did: None)


def test_empty_provider_rejected(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "myCorpus"}).json()["id"]
            r = client.post("/virtual-models", json={
                "name": "mymodel", "corpus_id": cid,
                "provider": "", "model": "llama3.1"})
            assert r.status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def test_virtual_model_crud(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "contracts"}).json()["id"]

            r = client.post("/virtual-models", json={
                "name": "contracts@local", "corpus_id": cid,
                "provider": "ollama", "model": "llama3.1"})
            assert r.status_code == 201
            vm_id = r.json()["id"]
            assert r.json()["name"] == "contracts@local"

            assert len(client.get("/virtual-models").json()) == 1
            assert client.get(f"/virtual-models/{vm_id}").json()["provider"] == "ollama"

            # duplicate name -> 409
            dup = client.post("/virtual-models", json={
                "name": "contracts@local", "corpus_id": cid,
                "provider": "p", "model": "m"})
            assert dup.status_code == 409

            # unknown corpus -> 404
            bad = client.post("/virtual-models", json={
                "name": "x", "corpus_id": 9999, "provider": "p", "model": "m"})
            assert bad.status_code == 404

            assert client.delete(f"/virtual-models/{vm_id}").status_code == 204
            assert client.get(f"/virtual-models/{vm_id}").status_code == 404
    finally:
        api.app.dependency_overrides.clear()

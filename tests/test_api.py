from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "cloudops-ai",
        "version": "0.1.0",
    }


def test_cluster_summary_returns_node_and_pod_counts(monkeypatch):
    from app import main

    class FakeNode:
        def __init__(self, name, ready):
            self.metadata = type("Metadata", (), {"name": name})()
            condition = type(
                "Condition",
                (),
                {"type": "Ready", "status": "True" if ready else "False"},
            )()
            self.status = type(
                "Status", (), {"conditions": [condition]}
            )()

    class FakePod:
        def __init__(self, phase):
            self.status = type(
                "Status",
                (),
                {"phase": phase, "container_statuses": []},
            )()

    class FakeCoreV1Api:
        def list_node(self):
            return type(
                "NodeList",
                (),
                {"items": [FakeNode("node-1", True), FakeNode("node-2", True)]},
            )()

        def list_pod_for_all_namespaces(self):
            return type(
                "PodList",
                (),
                {"items": [FakePod("Running"), FakePod("Pending")]},
            )()

    monkeypatch.setattr(main, "load_kubernetes_config", lambda: None)
    monkeypatch.setattr(main.client, "CoreV1Api", FakeCoreV1Api)

    with TestClient(app) as client:
        response = client.get("/cluster/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["cluster_status"] == "healthy"
    assert data["nodes"]["total"] == 2
    assert data["nodes"]["ready"] == 2
    assert data["pods"]["total"] == 2
    assert data["pods"]["running"] == 1
    assert data["pods"]["pending"] == 1


def test_cluster_summary_returns_503_when_kubernetes_fails(monkeypatch):
    from app import main

    def fail_to_load_config():
        raise RuntimeError("simulated Kubernetes failure")

    monkeypatch.setattr(main, "load_kubernetes_config", fail_to_load_config)

    with TestClient(app) as client:
        response = client.get("/cluster/summary")

    assert response.status_code == 503
    assert "Unable to retrieve cluster summary" in response.json()["detail"]

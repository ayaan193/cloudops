
from fastapi import FastAPI, HTTPException
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from app.database import init_db
from app.incidents import router as incidents_router
from app.diagnostics import router as diagnostics_router

app = FastAPI(
    title="CloudOps AI",
    description="Kubernetes operations and diagnostics API",
    version="0.1.0",
)
@app.on_event("startup")
def startup():
    init_db()


app.include_router(incidents_router)
app.include_router(diagnostics_router)

@app.get("/health")
def health():
    """Check whether the API is running."""
    return {
        "status": "healthy",
        "service": "cloudops-ai",
        "version": "0.1.0",
    }


def load_kubernetes_config():
    """Load local kubeconfig or in-cluster credentials."""
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()


@app.get("/cluster/summary")
def cluster_summary():
    """Return a read-only summary of Kubernetes cluster health."""
    try:
        load_kubernetes_config()

        core_v1 = client.CoreV1Api()
        nodes = core_v1.list_node().items
        pods = core_v1.list_pod_for_all_namespaces().items

        node_summary = []
        for node in nodes:
            conditions = node.status.conditions or []
            ready = any(
                condition.type == "Ready" and condition.status == "True"
                for condition in conditions
            )

            node_summary.append({
                "name": node.metadata.name,
                "ready": ready,
            })

        pod_summary = {
            "total": len(pods),
            "running": sum(
                pod.status.phase == "Running" for pod in pods
            ),
            "pending": sum(
                pod.status.phase == "Pending" for pod in pods
            ),
            "failed": sum(
                pod.status.phase == "Failed" for pod in pods
            ),
            "problem_containers": sum(
                1
                for pod in pods
                for container_status in (
                    pod.status.container_statuses or []
                )
                if (
                    container_status.state
                    and (
                        container_status.state.waiting
                        and container_status.state.waiting.reason
                        in {
                            "ImagePullBackOff",
                            "ErrImagePull",
                            "CrashLoopBackOff",
                            "CreateContainerConfigError",
                        }
                    )
                )
            ),
        }

        return {
            "cluster_status": (
                "healthy"
                if node_summary and all(n["ready"] for n in node_summary)
                else "degraded"
            ),
            "nodes": {
                "total": len(node_summary),
                "ready": sum(n["ready"] for n in node_summary),
                "details": node_summary,
            },
            "pods": pod_summary,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to retrieve cluster summary: {exc}",
        ) from exc

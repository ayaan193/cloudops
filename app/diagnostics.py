
from fastapi import APIRouter, HTTPException, Query
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from pydantic import BaseModel, Field
from app.database import get_connection

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])

FAILURE_REASONS = {
    "ImagePullBackOff": "medium",
    "ErrImagePull": "medium",
    "CrashLoopBackOff": "high",
    "CreateContainerConfigError": "high",
    "CreateContainerError": "high",
}


def load_cluster_config():
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()


@router.post("/scan")
def scan_pods(
    namespace: str = Query(default="cloudops-lab", min_length=1)
):
    """Scan a namespace and persist newly detected Pod failures."""
    try:
        load_cluster_config()
        core_v1 = client.CoreV1Api()
        pods = core_v1.list_namespaced_pod(
            namespace=namespace
        ).items

        detected = []
        saved = []
        existing = []

        with get_connection() as conn:
            for pod in pods:
                pod_name = pod.metadata.name
                issue = None

                # Detect a Pod that has entered the Failed phase.
                if pod.status.phase == "Failed":
                    issue = {
                        "reason": "PodFailed",
                        "severity": "high",
                        "container": None,
                        "message": pod.status.message or (
                            "Pod entered the Failed phase."
                        ),
                    }

                # Detect common container startup/runtime failures.
                for status in (pod.status.container_statuses or []):
                    waiting = (
                        status.state.waiting
                        if status.state else None
                    )

                    if waiting and waiting.reason in FAILURE_REASONS:
                        issue = {
                            "reason": waiting.reason,
                            "severity": FAILURE_REASONS[waiting.reason],
                            "container": status.name,
                            "message": waiting.message or (
                                "Container is waiting due to a failure."
                            ),
                        }
                        break

                    terminated = (
                        status.state.terminated
                        if status.state else None
                    )
                    if terminated and terminated.exit_code != 0:
                        issue = {
                            "reason": "ContainerTerminated",
                            "severity": "high",
                            "container": status.name,
                            "message": (
                                f"Container exited with code "
                                f"{terminated.exit_code}: "
                                f"{terminated.reason or 'unknown reason'}"
                            ),
                        }
                        break

                if not issue:
                    continue

                title = f"{issue['reason']} detected in Pod {pod_name}"
                detected.append({
                    "pod": pod_name,
                    "reason": issue["reason"],
                    "severity": issue["severity"],
                })

                # Avoid creating another copy of an open incident
                # for the same Pod and failure type.
                row = conn.execute(
                    """
                    SELECT id FROM incidents
                    WHERE namespace = %s
                      AND resource_name = %s
                      AND title = %s
                      AND status IN ('open', 'investigating')
                    LIMIT 1
                    """,
                    (namespace, pod_name, title),
                ).fetchone()

                if row:
                    existing.append({
                        "pod": pod_name,
                        "incident_id": row[0],
                    })
                    continue

                row = conn.execute(
                    """
                    INSERT INTO incidents
                        (title, description, namespace,
                         resource_name, severity)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        title,
                        issue["message"],
                        namespace,
                        pod_name,
                        issue["severity"],
                    ),
                ).fetchone()

                saved.append({
                    "pod": pod_name,
                    "incident_id": row[0],
                    "reason": issue["reason"],
                })

        return {
            "namespace": namespace,
            "pods_scanned": len(pods),
            "failures_detected": len(detected),
            "incidents_created": len(saved),
            "existing_incidents": len(existing),
            "detected": detected,
            "created": saved,
            "already_recorded": existing,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Kubernetes diagnostic scan failed.",
        ) from exc

class ClusterDoctorProblem(BaseModel):
    name: str
    namespace: str
    status: str
    issue: str


class ClusterDoctorReport(BaseModel):
    cluster_healthy: bool
    namespace: str
    nodes_total: int = Field(ge=0)
    nodes_ready: int = Field(ge=0)
    pods_inspected: int = Field(ge=0)
    problems_found: int = Field(ge=0)
    problems: list[ClusterDoctorProblem] = Field(default_factory=list)


@router.post("/import")
def import_cluster_doctor_report(report: ClusterDoctorReport):
    """Import Go CLI findings into PostgreSQL as incidents."""
    if report.problems_found != len(report.problems):
        raise HTTPException(
            status_code=422,
            detail="problems_found must match the number of problems",
        )

    created = []
    already_recorded = []

    try:
        with get_connection() as conn:
            for problem in report.problems:
                # Use the namespace from each finding, not an arbitrary
                # namespace supplied separately by the caller.
                title = (
                    f"cluster-doctor: {problem.issue} "
                    f"in Pod {problem.name}"
                )

                severity = (
                    "high"
                    if any(
                        reason in problem.issue
                        for reason in (
                            "CrashLoopBackOff",
                            "CreateContainerConfigError",
                            "CreateContainerError",
                            "PodFailed",
                            "exited with code",
                        )
                    )
                    else "medium"
                )

                existing = conn.execute(
                    """
                    SELECT id FROM incidents
                    WHERE namespace = %s
                      AND resource_name = %s
                      AND title = %s
                      AND status IN ('open', 'investigating')
                    LIMIT 1
                    """,
                    (problem.namespace, problem.name, title),
                ).fetchone()

                if existing:
                    already_recorded.append(existing[0])
                    continue

                row = conn.execute(
                    """
                    INSERT INTO incidents
                        (title, description, namespace,
                         resource_name, severity)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        title,
                        f"Detected by Go cluster-doctor. "
                        f"Pod status: {problem.status}. "
                        f"Issue: {problem.issue}",
                        problem.namespace,
                        problem.name,
                        severity,
                    ),
                ).fetchone()

                created.append(row[0])

        return {
            "incidents_created": len(created),
            "incident_ids": created,
            "already_recorded": len(already_recorded),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to import diagnostic report.",
        ) from exc

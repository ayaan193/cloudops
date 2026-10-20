
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_connection

router = APIRouter(prefix="/incidents", tags=["Incidents"])


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    namespace: str = Field(default="cloudops-lab", max_length=100)
    resource_name: str | None = Field(default=None, max_length=200)
    severity: Literal["low", "medium", "high", "critical"] = "medium"

class IncidentStatusUpdate(BaseModel):
    status: Literal["open", "investigating", "resolved"]

class IncidentResponse(BaseModel):
    id: int
    title: str
    description: str
    namespace: str
    resource_name: str | None
    severity: str
    status: str
    created_at: datetime


@router.post("", response_model=IncidentResponse, status_code=201)
def create_incident(incident: IncidentCreate):
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO incidents
                    (title, description, namespace, resource_name, severity)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, title, description, namespace,
                          resource_name, severity, status, created_at
                """,
                (
                    incident.title,
                    incident.description,
                    incident.namespace,
                    incident.resource_name,
                    incident.severity,
                ),
            ).fetchone()

        return dict(row) if hasattr(row, "keys") else {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "namespace": row[3],
            "resource_name": row[4],
            "severity": row[5],
            "status": row[6],
            "created_at": row[7],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to save incident to the database.",
        ) from exc


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    limit: int = Query(default=50, ge=1, le=100),
):
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, description, namespace,
                       resource_name, severity, status, created_at
                FROM incidents
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "namespace": row[3],
                "resource_name": row[4],
                "severity": row[5],
                "status": row[6],
                "created_at": row[7],
            }
            for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve incidents from the database.",
        ) from exc

@router.patch("/{incident_id}/status", response_model=IncidentResponse)
def update_incident_status(
    incident_id: int,
    update: IncidentStatusUpdate,
):
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                UPDATE incidents
                SET status = %s
                WHERE id = %s
                RETURNING id, title, description, namespace,
                          resource_name, severity, status, created_at
                """,
                (update.status, incident_id),
            ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Incident not found",
            )

        return {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "namespace": row[3],
            "resource_name": row[4],
            "severity": row[5],
            "status": row[6],
            "created_at": row[7],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to update incident status.",
        ) from exc

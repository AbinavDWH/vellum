import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import SessionRecord, MessageRecord, PlanRecord
from app.requirements import requirements_manager

client = TestClient(app)


def test_conversational_turn_updates_requirements_and_avoids_hardcoded_questions():
    """Verify that general chat returns conversational status and updates requirements.md without rigid questions."""
    session_id = f"sess_chat_{uuid.uuid4().hex[:8]}"

    # 1. User starts with an exploratory conversation
    res = client.post(
        "/api/chat",
        json={
            "prompt": "I want to design a backend for a medical telemedicine platform with patient records and appointments",
            "session_id": session_id,
            "cloud_provider": "aws",
            "environment": "local",
        },
    )
    assert res.status_code == 200
    data = res.json()

    # Must be conversational (can include interactive clarification choices)
    assert data["status"] == "conversation"
    assert len(data["message"]) > 0
    assert data.get("requirements_md") is not None
    assert data["requirements_md"].startswith("# Spec") and "**Cloud Provider**" in data["requirements_md"]

    # Verify requirements.md was saved to DB and disk
    req_res = client.get(f"/api/sessions/{session_id}/requirements")
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert req_data["session_id"] == session_id
    assert "telemedicine" in req_data["requirements_md"].lower() or "patient" in req_data["requirements_md"].lower() or "architecture" in req_data["requirements_md"].lower()

    # 2. User clarifies/discusses database in a follow-up conversational turn
    res2 = client.post(
        "/api/chat",
        json={
            "prompt": "Let's use a PostgreSQL database with HIPAA compliant encryption and an S3 bucket for prescription scans",
            "session_id": session_id,
            "cloud_provider": "aws",
            "environment": "local",
        },
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "conversation"
    assert "PostgreSQL" in data2["requirements_md"] or "postgres" in data2["requirements_md"].lower()

    # 3. User is ready to plan: says "Looks good, plan this architecture"
    res3 = client.post(
        "/api/chat",
        json={
            "prompt": "Looks good, plan this architecture and generate terraform",
            "session_id": session_id,
            "cloud_provider": "aws",
            "environment": "local",
        },
    )
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["status"] == "plan_ready"
    assert data3["plan"] is not None
    assert data3["plan"]["plan_id"] is not None


def test_plan_from_session_requirements_endpoint():
    """Verify direct synthesis of infrastructure from requirements.md endpoint."""
    session_id = f"sess_req_plan_{uuid.uuid4().hex[:8]}"
    unique_bucket = f"analytics-logs-{uuid.uuid4().hex[:6]}"

    # Create session
    create_res = client.post("/api/sessions", json={"title": "Custom Spec Session"})
    assert create_res.status_code == 200
    sess_id = create_res.json()["id"]

    # Provide custom requirements markdown
    custom_md = f"""# Architecture Specification & Requirements

## 1. System Overview & Objective
Internal metrics analytics pipeline storing high-volume event logs.

## 2. Target Environment
- **Cloud Provider**: AWS
- **Environment**: local
- **Target Region**: us-east-1

## 3. Infrastructure Topology & Components
- **Networking**: VPC 10.0.0.0/16 with private database subnets
- **Storage**: S3 Bucket called {unique_bucket}

## 4. Database & Data Model
- **Engine**: PostgreSQL 15
- **Entities & Tables**:
  - `event_logs`: id (serial PK), event_name (varchar), payload (jsonb), created_at (timestamp)

## 5. Security, Reliability & Compliance
- **Backup & Retention**: Automated daily snapshots
"""
    put_res = client.put(f"/api/sessions/{sess_id}/requirements", json={"requirements_md": custom_md})
    assert put_res.status_code == 200
    assert put_res.json()["requirements_md"] == custom_md.strip()

    # Trigger plan directly from requirements
    plan_res = client.post(f"/api/sessions/{sess_id}/plan-from-requirements?environment=local")
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert plan_data["status"] == "plan_ready"
    assert plan_data["plan"] is not None
    assert plan_data["plan"]["generated_terraform"] is not None

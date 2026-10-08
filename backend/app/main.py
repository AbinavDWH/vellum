import os
import json
import uuid
import datetime
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.database import get_db, init_db, SessionLocal
from app.models import (
    PlanRecord,
    ApprovalRecord,
    ExecutionRecord,
    SessionRecord,
    MessageRecord,
    HealingAttemptRecord,
    RemediationKBRecord,
    ConnectionRecord,
)
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    ApprovalRequest,
    PlanResponse,
    ExecutionResult,
    VerificationResult,
    SessionResponse,
    SessionCreateRequest,
    SessionUpdateRequest,
    SessionMessageResponse,
    ReexecuteRequest,
    ReexecuteResult,
    ExecutionItemResponse,
    ErrorDetectionResponse,
    HealingAttemptResponse,
    RemediationKBItem,
    RemediationKBUpdateRequest,
    ConnectionResponse,
    ConnectionCreateRequest,
    ConnectionUpdateRequest,
    ConnectionTestResponse,
    ServicesUpdateRequest,
    LocalStackRestartResponse,
    RequirementsUpdateRequest,
    RequirementsResponse,
    ActiveAIRequest,
    WireTraceItem,
    WireTraceExportResponse,
    ThreeLegVerificationReport,
    ExecutionPolicy,
    TerminateExecutionRequest,
    ChatCancelRequest,
    SupervisorEventResponse,
)
from app.requirements import requirements_manager
from app.schemas.ir import UniversalIR
from app.llm.client import llm_client
from app.engines.orchestrator import orchestrator
from app.engines.execution_engine import execution_engine
from app.engines.verification_engine import verification_engine
from app.approval.engine import approval_engine
from app.audit.logger import audit_logger
from app.validation.policy import PolicyEngine, RiskLevel
from app.engines.rag_engine import rag_engine
from app.rag.service import get_rag_service
import time
from app.healing import self_healing_engine, error_detector, kb_manager
from app.healing.supervisor import healing_supervisor
from app.tracing.wire_trace import wire_trace_collector
from app.environment.inventory import environment_inventory
from app.validation.environment_conflict import environment_conflict_validator
from app.credentials.manager import credential_manager

logger = structlog.get_logger(__name__)

# Active cancellation tokens for in-flight chat requests
_chat_cancellation_tokens: set = set()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Autonomous NLP-driven Cloud Infrastructure & Database Architecture Engine",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory idempotency cache for re-execute requests: key -> (timestamp, response_dict)
_reexecute_idempotency_cache: Dict[str, Tuple[datetime.datetime, Dict[str, Any]]] = {}


def format_plan_response(r: PlanRecord, db: Optional[Session] = None) -> PlanResponse:
    ir_dict = json.loads(r.ir_json)
    ir = UniversalIR(**ir_dict)
    summary = approval_engine.format_plan_preview(ir)
    security_findings = json.loads(r.security_checks_json) if r.security_checks_json else []

    from app.target import resolve_target

    target = resolve_target(plan=r, ir=ir, db=db, allow_missing=True)
    target_env = target.environment or (ir.cloud.environment if ir.cloud else None) or "local"
    target_region = target.region
    account_id = target.account_id
    target_label = target.target_label
    conn_id = target.connection_id or r.connection_id

    return PlanResponse(
        plan_id=r.plan_id,
        status=r.status,
        intent=r.intent,
        risk_level=r.risk_level,
        requires_confirmation_text=bool(r.requires_confirmation_text),
        confirmation_phrase=r.confirmation_phrase,
        summary_preview=summary,
        ir=ir,
        generated_terraform=r.terraform_code,
        generated_sql=r.sql_code,
        estimated_cost_monthly=r.estimated_cost_monthly or 0.0,
        security_checks=security_findings,
        implementation_plan=ir.implementation_plan or orchestrator._build_implementation_plan(ir),
        connection_id=conn_id,
        environment=target_env,
        target_label=target_label,
        account_id=account_id,
        region=target_region,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        service = get_rag_service()
        if service.store.count_chunks() == 0:
            service.ingest_knowledge_base()
    except Exception as e:
        print(f"[WARN] Failed to auto-index RAG knowledge base on startup: {e}")


@app.get("/health")
@app.get("/api/health")
def health_check():
    status_info = llm_client.get_provider_status()
    is_online = status_info["active_online"]
    return {
        "status": "healthy" if is_online else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "single_ai_mode": True,
        "active_provider": status_info["active_provider"],
        "active_model": status_info["active_model"],
        "active_online": status_info["active_online"],
        "lm_studio_online": status_info["lm_studio_online"],
        "groq_online": status_info["groq_online"],
        "routing_mode": status_info["routing_mode"],
        "cloud_env": settings.CLOUD_ENV,
        "cloud_provider": settings.CLOUD_PROVIDER,
    }


@app.get("/api/ai/active")
@app.get("/api/ai/provider")
def get_active_ai():
    """Retrieve currently active single AI provider, active model, and status."""
    return llm_client.get_provider_status()


@app.post("/api/ai/active")
@app.post("/api/ai/provider")
def set_active_ai(payload: ActiveAIRequest):
    """Switch the single active AI provider and model immediately."""
    try:
        llm_client.set_active_provider(payload.provider, payload.model)
        return llm_client.get_provider_status()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/models")
def get_available_models():
    """List available LLM models from Groq and LM Studio for single AI selection."""
    models = []
    active_prov = llm_client.get_active_provider()
    active_model = llm_client._active_model

    # Groq models
    if llm_client.groq.is_configured():
        for gm in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
            is_act = (active_prov == "groq" and (active_model == gm or (not active_model and gm == llm_client.groq.default_model)))
            models.append({
                "id": f"groq:{gm}",
                "name": f"⚡ Groq • {gm}",
                "provider": "groq",
                "model_name": gm,
                "is_active": is_act,
            })

    # Local LM Studio models
    try:
        import httpx
        r = httpx.get(f"{settings.LM_STUDIO_URL}/models", timeout=3.0)
        if r.status_code == 200:
            for lm in r.json().get("data", []):
                mid = lm.get("id")
                if mid and not mid.startswith("text-embedding"):
                    is_act = (active_prov == "local" and (active_model == mid or not active_model))
                    models.append({
                        "id": f"local:{mid}",
                        "name": f"🖥️ Local • {mid}",
                        "provider": "local",
                        "model_name": mid,
                        "is_active": is_act,
                    })
    except Exception:
        pass

    if not any(m["provider"] == "local" for m in models):
        def_local = settings.LM_STUDIO_MODEL
        is_act = (active_prov == "local")
        models.append({
            "id": f"local:{def_local}",
            "name": f"🖥️ Local • {def_local}",
            "provider": "local",
            "model_name": def_local,
            "is_active": is_act,
        })

    return models


# ========================================================
# M-13: Persistent Chat Sessions API
# ========================================================

@app.get("/api/sessions", response_model=List[SessionResponse])
def list_sessions(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List persistent chat sessions, newest first, paginated."""
    query = db.query(SessionRecord).filter(SessionRecord.is_deleted == False)
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query = query.filter(SessionRecord.title.ilike(search_pattern))

    records = query.order_by(SessionRecord.updated_at.desc()).offset(offset).limit(limit).all()
    return [
        SessionResponse(
            id=s.id,
            title=s.title,
            status=s.status,
            message_count=s.message_count,
            last_plan_id=s.last_plan_id,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
            requirements_md=s.requirements_md,
        )
        for s in records
    ]


@app.post("/api/sessions", response_model=SessionResponse)
def create_session(request: Optional[SessionCreateRequest] = None, db: Session = Depends(get_db)):
    """Create a new chat session with default requirements.md."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    title = (request.title.strip() if request and request.title else None) or "New Infrastructure Session"
    cloud_provider = (request.cloud_provider if request and request.cloud_provider else "aws")
    environment = (request.environment if request and request.environment else "local")
    initial_md = requirements_manager.get_default_template(cloud_provider=cloud_provider, environment=environment)
    session = SessionRecord(
        id=session_id,
        title=title,
        status="active",
        message_count=0,
        requirements_md=initial_md,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    requirements_manager.save_requirements(session_id, initial_md, db=db)
    return SessionResponse(
        id=session.id,
        title=session.title,
        status=session.status,
        message_count=session.message_count,
        last_plan_id=session.last_plan_id,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        requirements_md=session.requirements_md,
    )


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Fetch session details with last plan and requirements specification."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    last_plan_data = None
    if session.last_plan_id:
        plan_rec = db.query(PlanRecord).filter(PlanRecord.plan_id == session.last_plan_id).first()
        if plan_rec:
            last_plan_data = format_plan_response(plan_rec).model_dump()

    req_md = session.requirements_md or requirements_manager.get_requirements(session_id=session.id, db=db)

    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "message_count": session.message_count,
        "last_plan_id": session.last_plan_id,
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else "",
        "requirements_md": req_md,
        "last_plan": last_plan_data,
    }


@app.get("/api/sessions/{session_id}/messages", response_model=List[SessionMessageResponse])
def get_session_messages(session_id: str, db: Session = Depends(get_db)):
    """Retrieve full chronological conversation thread for a session."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        # Check if default session or legacy
        messages = db.query(MessageRecord).filter(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at.asc()).all()
        if not messages:
            return []
    else:
        messages = db.query(MessageRecord).filter(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at.asc()).all()

    results = []
    for m in messages:
        clarification = json.loads(m.clarification_json) if m.clarification_json else None
        results.append(
            SessionMessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                plan_id=m.plan_id,
                created_at=m.created_at.isoformat() if m.created_at else "",
                clarification=clarification,
            )
        )
    return results


@app.patch("/api/sessions/{session_id}", response_model=SessionResponse)
def rename_session(session_id: str, request: SessionUpdateRequest, db: Session = Depends(get_db)):
    """Rename a chat session title."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not request.title or not request.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    session.title = request.title.strip()
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    return SessionResponse(
        id=session.id,
        title=session.title,
        status=session.status,
        message_count=session.message_count,
        last_plan_id=session.last_plan_id,
        created_at=session.created_at.isoformat() if session.created_at else "",
        updated_at=session.updated_at.isoformat() if session.updated_at else "",
    )


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Soft-delete a chat session (audit-logged). Audit records remain immutable."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.is_deleted = True
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    audit_logger.log(
        event_type="SESSION_DELETED",
        plan_id=session.last_plan_id,
        risk_level="low",
        action_by="human_operator",
        details={"session_id": session_id, "title": session.title},
        db=db,
    )

    return {"status": "deleted", "id": session_id}


# ========================================================
# Requirements Specification (requirements.md) API
# ========================================================

@app.get("/api/sessions/{session_id}/requirements", response_model=RequirementsResponse)
def get_session_requirements(session_id: str, db: Session = Depends(get_db)):
    """Get the current Markdown architecture specification (requirements.md) for a session."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    md = requirements_manager.get_requirements(session_id=session_id, db=db)
    file_path = str(requirements_manager.get_file_path(session_id))
    return RequirementsResponse(
        session_id=session_id,
        requirements_md=md,
        file_path=file_path,
        updated_at=session.updated_at.isoformat() if session.updated_at else datetime.datetime.utcnow().isoformat(),
    )


@app.put("/api/sessions/{session_id}/requirements", response_model=RequirementsResponse)
def update_session_requirements(session_id: str, request: RequirementsUpdateRequest, db: Session = Depends(get_db)):
    """Directly update the session requirements.md architecture specification."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    saved = requirements_manager.save_requirements(session_id=session_id, content=request.requirements_md, db=db)
    session.requirements_md = saved
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    audit_logger.log(
        event_type="REQUIREMENTS_UPDATED",
        plan_id=session.last_plan_id,
        risk_level="low",
        action_by="human_operator",
        details={"session_id": session_id, "char_count": len(saved)},
        db=db,
    )

    return RequirementsResponse(
        session_id=session_id,
        requirements_md=saved,
        file_path=str(requirements_manager.get_file_path(session_id)),
        updated_at=session.updated_at.isoformat(),
    )


@app.post("/api/sessions/{session_id}/plan-from-requirements", response_model=ChatResponse)
def plan_from_session_requirements(
    session_id: str,
    cloud_provider: Optional[str] = "aws",
    environment: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Trigger plan generation directly from the accumulated requirements.md document."""
    session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    response = orchestrator.plan_from_requirements(
        session_id=session_id,
        cloud_provider=cloud_provider or "aws",
        environment=environment,
        db=db,
        model=model,
        provider=provider,
    )

    # Store assistant response and plan link in messages table
    plan_id = response.plan.plan_id if response.plan else None
    asst_msg = MessageRecord(
        id=f"msg_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        role="assistant",
        content=response.message,
        plan_id=plan_id,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(asst_msg)
    session.message_count += 1
    if plan_id:
        session.last_plan_id = plan_id
    if response.requirements_md:
        session.requirements_md = response.requirements_md
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    return response


@app.post("/api/chat/cancel")
def cancel_chat(req: ChatCancelRequest):
    """Cancel in-flight chat processing for a session (M-20)."""
    _chat_cancellation_tokens.add(req.session_id)
    return {"status": "cancelled", "session_id": req.session_id}


@app.post("/api/chat/stop/{session_id}")
def stop_chat_session(session_id: str):
    """Stop/cancel in-flight chat streaming for a session (F8 / M-20)."""
    _chat_cancellation_tokens.add(session_id)
    return {"status": "stopped", "session_id": session_id}


# ========================================================
# Chat Pipeline (Write-Through Session Persistence)
# ========================================================

@app.post("/api/chat", response_model=ChatResponse)
def handle_chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Process user natural language infrastructure requirement with persistent session memory (M-13)."""
    try:
        session_id = request.session_id or "default"
        if session_id in _chat_cancellation_tokens:
            _chat_cancellation_tokens.discard(session_id)
            raise HTTPException(status_code=499, detail="Client cancelled chat request.")

        # 1. Fetch or create persistent SessionRecord
        session = db.query(SessionRecord).filter(SessionRecord.id == session_id, SessionRecord.is_deleted == False).first()
        clean_prompt = request.prompt.strip()
        auto_title = clean_prompt[:40] + ("..." if len(clean_prompt) > 40 else "")

        if not session:
            session = SessionRecord(
                id=session_id,
                title=auto_title or "New Infrastructure Session",
                status="active",
                message_count=0,
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            )
            db.add(session)
            db.commit()
            db.refresh(session)
        elif session.message_count == 0:
            session.title = auto_title or session.title

        # 2. Store user message in persistent messages table
        user_msg = MessageRecord(
            id=f"msg_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="user",
            content=request.prompt,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(user_msg)
        session.message_count += 1
        session.updated_at = datetime.datetime.utcnow()
        db.commit()

        # Legacy RAG memory store
        rag_engine.save_message(
            sender="user",
            text=request.prompt,
            session_id=session_id,
            db=db,
        )

        # 3. Process via orchestrator
        response = orchestrator.process_natural_language(
            prompt=request.prompt,
            cloud_provider=request.cloud_provider or "aws",
            environment=request.environment,
            session_id=session_id,
            db=db,
            model=request.model,
            provider=request.provider,
        )

        # 4. Store assistant response and plan link in persistent messages table
        plan_id = response.plan.plan_id if response.plan else None
        clarification_dict = response.clarification.model_dump() if response.clarification else None
        asst_msg = MessageRecord(
            id=f"msg_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="assistant",
            content=response.message,
            plan_id=plan_id,
            clarification_json=json.dumps(clarification_dict) if clarification_dict else None,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(asst_msg)
        session.message_count += 1
        if plan_id:
            session.last_plan_id = plan_id
        if response.requirements_md:
            session.requirements_md = response.requirements_md
        session.updated_at = datetime.datetime.utcnow()
        db.commit()

        # Legacy RAG memory
        rag_engine.save_message(
            sender="assistant",
            text=response.message,
            session_id=session_id,
            plan_id=plan_id,
            clarification=clarification_dict,
            db=db,
        )

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/history")
def get_chat_history(session_id: str = "default", limit: int = 100, db: Session = Depends(get_db)):
    """Retrieve conversation history stored in RAG memory."""
    messages = rag_engine.get_history(session_id=session_id, limit=limit, db=db)
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/chat/history")
def clear_chat_history(session_id: str = "default", db: Session = Depends(get_db)):
    """Clear conversation history stored in RAG memory."""
    rag_engine.clear_history(session_id=session_id, db=db)
    return {"status": "cleared", "session_id": session_id}


@app.get("/api/chat/rag/context")
def get_rag_context(prompt: str, session_id: str = "default", db: Session = Depends(get_db)):
    """Retrieve RAG context for a given requirement query."""
    ctx = rag_engine.retrieve_context(prompt, session_id=session_id, db=db)
    return {"prompt": prompt, "rag_context": ctx}


@app.post("/api/rag/ingest")
def trigger_rag_ingest():
    service = get_rag_service()
    return service.ingest_knowledge_base(force_reindex=True)


@app.get("/api/rag/stats")
def get_rag_stats():
    service = get_rag_service()
    return service.get_stats()


@app.post("/api/rag/search")
def search_rag(query: str, top_k: int = 5, domain: Optional[str] = None):
    service = get_rag_service()
    results = service.search(query=query, top_k=top_k, domain=domain)
    return [
        {
            "citation_tag": r.citation_tag,
            "title": r.title,
            "domain": r.domain,
            "resource_type": r.resource_type,
            "final_score": round(r.final_score, 4),
            "dense_score": round(r.dense_score, 4),
            "sparse_score": round(r.sparse_score, 4),
            "content": r.content,
        }
        for r in results
    ]


@app.post("/api/rag/grounded-context")
def get_grounded_context(query: str):
    service = get_rag_service()
    ctx = service.assemble_grounded_context(query=query)
    return {
        "formatted_context": ctx.formatted_context,
        "has_sufficient_context": ctx.has_sufficient_context,
        "total_tokens_estimate": ctx.total_tokens_estimate,
        "domain_breakdown": ctx.domain_breakdown,
        "citations": [
            {
                "citation_tag": c.citation_tag,
                "title": c.title,
                "domain": c.domain,
                "resource_type": c.resource_type,
                "final_score": round(c.final_score, 4),
            }
            for c in ctx.citations
        ],
    }


@app.get("/api/rag/traces")
def get_rag_traces(limit: int = 50):
    service = get_rag_service()
    return service.get_traces(limit=limit)


@app.get("/api/rag/metrics")
def get_rag_metrics():
    service = get_rag_service()
    return service.tracer.get_metrics()


@app.post("/api/rag/eval")
def run_rag_evaluation(top_k: int = 5):
    service = get_rag_service()
    result = service.run_benchmark(top_k=top_k)
    return result.model_dump()


# ========================================================
# Plans API
# ========================================================

@app.get("/api/plans")
def list_plans(limit: int = 50, db: Session = Depends(get_db)):
    """List recent infrastructure plans."""
    records = db.query(PlanRecord).order_by(PlanRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "plan_id": r.plan_id,
            "prompt": r.prompt,
            "intent": r.intent,
            "risk_level": r.risk_level,
            "status": r.status,
            "estimated_cost_monthly": r.estimated_cost_monthly,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@app.get("/api/plans/{plan_id}", response_model=PlanResponse)
def get_plan_details(plan_id: str, db: Session = Depends(get_db)):
    """Fetch full plan details by ID."""
    r = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Plan not found")
    return format_plan_response(r)


@app.post("/api/plans/{plan_id}/approval")
def submit_approval(
    plan_id: str,
    request: ApprovalRequest,
    db: Session = Depends(get_db),
):
    """Human submits approval, rejection, or modification for a plan."""
    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if request.decision == "approve":
        # Check confirmation text if required
        if plan.requires_confirmation_text:
            if not request.confirmation_text or request.confirmation_text.strip().upper() != (plan.confirmation_phrase or "").upper():
                raise HTTPException(
                    status_code=400,
                    detail=f"Confirmation phrase mismatch. Expected: '{plan.confirmation_phrase}'",
                )

        # Check if this approval is for a re-execution
        existing_runs = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).count()
        if existing_runs > 0:
            audit_logger.log(
                event_type="REEXEC_APPROVED",
                plan_id=plan_id,
                risk_level=plan.risk_level,
                action_by="human_operator",
                details={"decision": "approve", "next_run_number": existing_runs + 1},
                db=db,
            )

        # Auto-rescan on approval time if cache is stale (closes most of the TOCTOU window)
        plan_env = "local"
        if plan.ir_json:
            try:
                p_ir = json.loads(plan.ir_json)
                plan_env = p_ir.get("cloud", {}).get("environment", "local")
            except Exception:
                pass
        current_snap = environment_inventory.get_snapshot(environment=plan_env, force_rescan=False, db=db)
        if current_snap.is_stale(60.0):
            environment_inventory.get_snapshot(environment=plan_env, force_rescan=True, plan_id=plan_id, db=db)

        plan.status = "approved"
        if request.custom_terraform:
            plan.terraform_code = request.custom_terraform
            plan_file = f"{settings.TERRAFORM_WORKSPACE}/{plan_id}/main.tf"
            try:
                with open(plan_file, "w") as f:
                    f.write(request.custom_terraform)
            except Exception:
                pass

        if request.custom_sql:
            plan.sql_code = request.custom_sql

        approval_rec = ApprovalRecord(
            plan_id=plan_id,
            decision="approve",
            confirmation_text=request.confirmation_text,
            reviewer="human_operator",
        )
        db.add(approval_rec)
        db.commit()

        audit_logger.log(
            event_type="APPROVAL_GRANTED",
            plan_id=plan_id,
            risk_level=plan.risk_level,
            action_by="human_operator",
            details={"decision": "approve"},
            db=db,
        )

        return {"status": "approved", "plan_id": plan_id, "message": "Plan approved. Ready for execution."}

    elif request.decision == "reject":
        plan.status = "rejected"
        approval_rec = ApprovalRecord(
            plan_id=plan_id,
            decision="reject",
            reviewer="human_operator",
        )
        db.add(approval_rec)
        db.commit()

        audit_logger.log(
            event_type="APPROVAL_REJECTED",
            plan_id=plan_id,
            risk_level=plan.risk_level,
            action_by="human_operator",
            details={"decision": "reject"},
            db=db,
        )

        return {"status": "rejected", "plan_id": plan_id, "message": "Plan rejected by user."}

    elif request.decision == "modify":
        current_ir = UniversalIR(**json.loads(plan.ir_json))
        revised_ir = llm_client.revise_plan(current_ir, request.modifications or "Make modifications requested")
        
        return orchestrator.process_natural_language(
            prompt=f"{plan.prompt} (Modifications: {request.modifications})",
            cloud_provider=revised_ir.cloud.provider if revised_ir.cloud else "aws",
            environment=revised_ir.cloud.environment if revised_ir.cloud else None,
            db=db,
        )


@app.post("/api/plans/{plan_id}/execute", response_model=ExecutionResult)
def execute_plan(plan_id: str, db: Session = Depends(get_db)):
    """Execute an approved plan."""
    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if settings.HUMAN_APPROVAL_REQUIRED and plan.status not in ["approved", "awaiting_approval"]:
        if plan.status == "completed":
            exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).order_by(ExecutionRecord.id.desc()).first()
            if exec_rec:
                return ExecutionResult(
                    plan_id=plan_id,
                    status=exec_rec.status,
                    success=exec_rec.success,
                    run_number=exec_rec.run_number or 1,
                    resources_created=exec_rec.resources_created,
                    resources_updated=exec_rec.resources_updated,
                    resources_deleted=exec_rec.resources_deleted,
                    terraform_output=exec_rec.terraform_output or "",
                    sql_output=exec_rec.sql_output or "",
                    error_message=exec_rec.error_message,
                    execution_time_seconds=exec_rec.duration_seconds or 0.0,
                )
        elif plan.status in ["failed", "halted"]:
            plan.status = "approved"
            db.commit()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Plan cannot be executed in current status: '{plan.status}'",
            )

    res = orchestrator.execute_approved_plan(plan_id=plan_id, db=db)
    return res


# ========================================================
# M-13: Safety-First Re-Execution API
# ========================================================

@app.post("/api/plans/{plan_id}/re-execute", response_model=ReexecuteResult)
def reexecute_plan(
    plan_id: str,
    request: Optional[ReexecuteRequest] = None,
    idempotency_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    M-13 Safety-First Re-execution Flow:
    1. Check idempotency key: duplicate submits ignored.
    2. Run dry-run verification against live infrastructure.
    3. If NO changes: return 'Infrastructure already matches plan' -> nothing executes, audit REEXEC_NOOP.
    4. If drift/changes detected: calculate diff, set plan status to awaiting_approval,
       require fresh human approval (with typed confirmation phrase if destructive).
    """
    # 1. Idempotency check
    idempotency_key = (request.idempotency_key if request and request.idempotency_key else None) or idempotency_header
    now = datetime.datetime.utcnow()
    if idempotency_key:
        if idempotency_key in _reexecute_idempotency_cache:
            cache_time, cached_res = _reexecute_idempotency_cache[idempotency_key]
            if (now - cache_time).total_seconds() < 60:
                logger.info("reexecute_idempotency_hit", key=idempotency_key, plan_id=plan_id)
                return ReexecuteResult(**cached_res)

    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    ir_dict = json.loads(plan.ir_json)
    ir = UniversalIR(**ir_dict)

    from app.target import resolve_target

    target = resolve_target(plan=plan, ir=ir, db=db, strict_prod=False, allow_missing=True)
    plan_env = target.environment or "local"
    region = target.region
    aws_access_key = target.aws_access_key
    aws_secret_key = target.aws_secret_key
    account_id = target.account_id

    # 2. Dry-run verification (does not apply any changes)
    report = verification_engine.verify(
        plan_id=plan_id,
        expected_ir=ir,
        environment=plan_env,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        region=region,
        account_id=account_id,
        db=db,
    )
    has_drift = report.get("drift_detected", False) or len(report.get("missing_resources", [])) > 0

    if not has_drift:
        # Case A: Infrastructure matches plan! Zero-op.
        audit_logger.log(
            event_type="REEXEC_NOOP",
            plan_id=plan_id,
            risk_level=plan.risk_level,
            action_by="human_operator",
            details={
                "message": "Infrastructure already matches plan",
                "verified_count": report.get("resources_verified", 0),
            },
            db=db,
        )
        res_data = {
            "plan_id": plan_id,
            "status": "noop",
            "has_changes": False,
            "message": "Infrastructure already matches plan",
            "diff": {
                "verified": report.get("resources_verified", 0),
                "missing": [],
            },
            "requires_confirmation_text": False,
        }
        if idempotency_key:
            _reexecute_idempotency_cache[idempotency_key] = (now, res_data)
        return ReexecuteResult(**res_data)

    # Case B: Drift / Changes detected!
    diff = {
        "missing": report.get("missing_resources", []),
        "verified": report.get("resources_verified", 0),
        "expected": report.get("expected_resources", []),
        "found": report.get("found_resources", []),
    }

    # Reclassify risk and mandate fresh human approval
    risk_level_eval, requires_conf, conf_phrase = PolicyEngine.evaluate_risk(ir)
    risk_level = risk_level_eval.value if hasattr(risk_level_eval, "value") else str(risk_level_eval).lower()
    if len(report.get("missing_resources", [])) > 0:
        risk_level = "high"
        requires_conf = True
        conf_phrase = f"RESTORE {plan_id[:8].upper()}"

    plan.status = "awaiting_approval"
    plan.risk_level = risk_level
    plan.requires_confirmation_text = requires_conf
    plan.confirmation_phrase = conf_phrase
    db.commit()

    audit_logger.log(
        event_type="REEXEC_DRIFT_DETECTED",
        plan_id=plan_id,
        risk_level=plan.risk_level,
        action_by="human_operator",
        details={
            "diff": diff,
            "missing_resources": report.get("missing_resources", []),
            "risk_level": risk_level,
        },
        db=db,
    )
    audit_logger.log(
        event_type="REEXEC_REQUESTED",
        plan_id=plan_id,
        risk_level=plan.risk_level,
        action_by="human_operator",
        details={"plan_id": plan_id, "action": "re-execute"},
        db=db,
    )

    plan_response = format_plan_response(plan)
    res_data = {
        "plan_id": plan_id,
        "status": "drift_detected",
        "has_changes": True,
        "message": f"Drift detected: {len(report.get('missing_resources', []))} resources need restoration. Fresh human approval required.",
        "diff": diff,
        "requires_confirmation_text": requires_conf,
        "confirmation_phrase": conf_phrase,
        "plan": plan_response,
    }
    if idempotency_key:
        _reexecute_idempotency_cache[idempotency_key] = (now, res_data)
    return ReexecuteResult(**res_data)


# ========================================================
# Executions History API
# ========================================================

@app.get("/api/executions", response_model=List[ExecutionItemResponse])
def list_executions(limit: int = 50, db: Session = Depends(get_db)):
    """List execution records with run numbers."""
    records = db.query(ExecutionRecord).order_by(ExecutionRecord.id.desc()).limit(limit).all()
    return [
        ExecutionItemResponse(
            id=r.id,
            plan_id=r.plan_id,
            run_number=r.run_number or 1,
            status=r.status,
            success=r.success,
            resources_created=r.resources_created,
            resources_updated=r.resources_updated,
            resources_deleted=r.resources_deleted,
            terraform_output=r.terraform_output,
            sql_output=r.sql_output,
            error_message=r.error_message,
            duration_seconds=r.duration_seconds or 0.0,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            resource_checklist=json.loads(r.resource_checklist_json) if getattr(r, "resource_checklist_json", None) and r.resource_checklist_json != "[]" else None,
        )
        for r in records
    ]


@app.get("/api/plans/{plan_id}/executions", response_model=List[ExecutionItemResponse])
def list_plan_executions(plan_id: str, db: Session = Depends(get_db)):
    """List all execution runs for a specific plan."""
    records = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).order_by(ExecutionRecord.run_number.asc()).all()
    return [
        ExecutionItemResponse(
            id=r.id,
            plan_id=r.plan_id,
            run_number=r.run_number or 1,
            status=r.status,
            success=r.success,
            resources_created=r.resources_created,
            resources_updated=r.resources_updated,
            resources_deleted=r.resources_deleted,
            terraform_output=r.terraform_output,
            sql_output=r.sql_output,
            error_message=r.error_message,
            duration_seconds=r.duration_seconds or 0.0,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            resource_checklist=json.loads(r.resource_checklist_json) if getattr(r, "resource_checklist_json", None) and r.resource_checklist_json != "[]" else None,
        )
        for r in records
    ]


@app.post("/api/plans/{plan_id}/verify", response_model=VerificationResult)
def verify_plan(plan_id: str, db: Session = Depends(get_db)):
    """Verify state and detect drift against LocalStack."""
    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    ir = UniversalIR(**json.loads(plan.ir_json))

    from app.target import resolve_target

    target = resolve_target(plan=plan, ir=ir, db=db, strict_prod=False, allow_missing=True)
    plan_env = target.environment or "local"
    region = target.region
    aws_access_key = target.aws_access_key
    aws_secret_key = target.aws_secret_key
    account_id = target.account_id

    report = verification_engine.verify(
        plan_id=plan_id,
        expected_ir=ir,
        environment=plan_env,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        region=region,
        account_id=account_id,
        db=db,
    )

    audit_logger.log(
        event_type="VERIFICATION_PASSED" if not report["drift_detected"] else "DRIFT_DETECTED",
        plan_id=plan_id,
        risk_level=plan.risk_level,
        details=report,
        db=db,
    )

    return VerificationResult(
        plan_id=plan_id,
        status=report["status"],
        drift_detected=report["drift_detected"],
        resources_verified=report["resources_verified"],
        expected_resources=report["expected_resources"],
        found_resources=report["found_resources"],
        missing_resources=report["missing_resources"],
        details=report.get("details", {}),
        target_environment=report.get("target_environment"),
        audited_account_id=report.get("audited_account_id"),
        audited_region=report.get("audited_region"),
        audited_target_label=report.get("audited_target_label"),
        audited_at=report.get("audited_at"),
        error_message=report.get("error_message"),
        three_leg=report.get("three_leg"),
    )


@app.post("/api/plans/{plan_id}/rollback", response_model=ExecutionResult)
def rollback_plan(plan_id: str, db: Session = Depends(get_db)):
    """Roll back infrastructure resources created by a plan."""
    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan_dir = os.path.join(settings.TERRAFORM_WORKSPACE, plan_id)
    if not os.path.exists(plan_dir):
        raise HTTPException(status_code=400, detail=f"Plan workspace does not exist: {plan_dir}")

    result = execution_engine.rollback(plan_dir=plan_dir, plan_id=plan_id, db=db)
    return result


# ========================================================
# M-19 & M-20: Wire Trace, Supervisor Feed & Runtime Control APIs
# ========================================================

@app.get("/api/plans/{plan_id}/traces", response_model=List[WireTraceItem])
def get_plan_wire_traces(plan_id: str, db: Session = Depends(get_db)):
    """Retrieve wire-level AWS trace records for a plan (M-19)."""
    traces = wire_trace_collector.get_traces(plan_id, db=db)
    return [
        WireTraceItem(
            seq=t.seq,
            ts=t.ts,
            plan_id=t.plan_id,
            execution_id=t.execution_id,
            connection_id=t.connection_id,
            account=t.account,
            region=t.region,
            service=t.service,
            operation=t.operation,
            source=t.source,
            params_masked=t.params_masked or {},
            http_status=t.http_status,
            error_code=t.error_code,
            error_message=t.error_message,
            request_id=t.request_id,
            latency_ms=t.latency_ms,
            cloudtrail_confirmed=t.cloudtrail_confirmed,
        )
        for t in traces
    ]


@app.get("/api/plans/{plan_id}/traces/export", response_model=WireTraceExportResponse)
def export_plan_wire_traces(plan_id: str, db: Session = Depends(get_db)):
    """Export wire-level traces with SHA-256 fingerprint for non-repudiation audit (M-19)."""
    traces = wire_trace_collector.get_traces(plan_id, db=db)
    json_str, sha256_hash = wire_trace_collector.export_trace_json(plan_id, db=db)
    items = [
        WireTraceItem(
            seq=t.seq,
            ts=t.ts,
            plan_id=t.plan_id,
            execution_id=t.execution_id,
            connection_id=t.connection_id,
            account=t.account,
            region=t.region,
            service=t.service,
            operation=t.operation,
            source=t.source,
            params_masked=t.params_masked or {},
            http_status=t.http_status,
            error_code=t.error_code,
            error_message=t.error_message,
            request_id=t.request_id,
            latency_ms=t.latency_ms,
            cloudtrail_confirmed=t.cloudtrail_confirmed,
        )
        for t in traces
    ]
    return WireTraceExportResponse(
        plan_id=plan_id,
        traces_count=len(items),
        trace_hash=sha256_hash,
        exported_at=datetime.datetime.utcnow().isoformat(),
        traces=items,
    )


@app.get("/api/plans/{plan_id}/supervisor/feed", response_model=List[SupervisorEventResponse])
def get_supervisor_feed(plan_id: str, db: Session = Depends(get_db)):
    """Retrieve real-time event feed from Always-On Healing Supervisor (M-20)."""
    events = healing_supervisor.get_feed(plan_id, db=db)
    return [
        SupervisorEventResponse(
            seq=e.seq,
            timestamp=e.timestamp,
            plan_id=e.plan_id,
            execution_id=e.execution_id,
            phase=e.phase,
            signature=e.signature,
            diagnosis=e.diagnosis,
            decision=e.decision,
            confidence=e.confidence,
            reasoning=e.reasoning,
            message=e.message,
        )
        for e in events
    ]


@app.post("/api/plans/{plan_id}/terminate")
def terminate_plan_execution(plan_id: str, request: TerminateExecutionRequest, db: Session = Depends(get_db)):
    """
    Operator-controlled runtime execution termination (M-20).
    Graceful mode: sends SIGINT (allows Terraform to write final state & release locks).
    Force mode: sends SIGKILL + deterministic process reaping + state reconciliation.
    """
    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan_dir = f"{settings.TERRAFORM_WORKSPACE}/{plan_id}"
    res = execution_engine.terminate_execution(
        plan_id=plan_id,
        force=request.force,
        plan_dir=plan_dir if os.path.exists(plan_dir) else None,
        db=db,
    )
    return res


@app.post("/api/executions/{id}/terminate")
def terminate_execution_endpoint(id: str, request: Optional[TerminateExecutionRequest] = None, db: Session = Depends(get_db)):
    """
    Operator-controlled runtime execution termination (F8 / M-20).
    Supports either integer execution ID or plan ID string.
    Graceful mode (click 1): SIGINT.
    Force mode (click 2): SIGKILL + deterministic process reaping + state reconciliation.
    """
    force = request.force if request else False
    plan_id = id
    if id.isdigit():
        exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.id == int(id)).first()
        if exec_rec and exec_rec.plan_id:
            plan_id = exec_rec.plan_id

    plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Execution or Plan not found")

    plan_dir = f"{settings.TERRAFORM_WORKSPACE}/{plan_id}"
    res = execution_engine.terminate_execution(
        plan_id=plan_id,
        force=force,
        plan_dir=plan_dir if os.path.exists(plan_dir) else None,
        db=db,
    )
    return res


@app.get("/api/audit")
def get_audit_trail(limit: int = 50):
    """Retrieve immutable audit logs."""
    return audit_logger.get_all_logs(limit=limit)


# ========================================================
# M-14: Self-Healing & Remediation APIs
# ========================================================

@app.get("/api/executions/{exec_id}/errors", response_model=List[ErrorDetectionResponse])
def get_execution_errors(exec_id: str, db: Session = Depends(get_db)):
    """Retrieve detected errors and classification for an execution or plan."""
    exec_rec = None
    if exec_id.isdigit():
        exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.id == int(exec_id)).first()
    if not exec_rec:
        exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == exec_id).order_by(ExecutionRecord.id.desc()).first()

    results = []
    heals = []
    if exec_rec:
        heals = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.execution_id == exec_rec.id).all()
    else:
        heals = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.plan_id == exec_id).all()

    seen_sigs = set()
    for h in heals:
        if h.error_signature not in seen_sigs:
            seen_sigs.add(h.error_signature)
            results.append(ErrorDetectionResponse(
                signature=h.error_signature,
                error_class=h.error_class,
                message=h.error_message or "",
                is_unfixable=h.remediation_class == "halted",
                remediation_class=h.remediation_class,
                diagnosis=h.reasoning,
            ))

    if not results and exec_rec:
        text = f"{exec_rec.error_message or ''}\n{exec_rec.terraform_output or ''}"
        detected = error_detector.detect(text)
        if detected:
            results.append(ErrorDetectionResponse(
                signature=detected.signature,
                error_class=detected.error_class,
                message=detected.message,
                is_unfixable=detected.is_unfixable,
                remediation_class=detected.remediation_class,
                diagnosis=detected.diagnosis,
            ))

    return results


@app.get("/api/executions/{exec_id}/heals", response_model=List[HealingAttemptResponse])
def get_execution_heals(exec_id: str, db: Session = Depends(get_db)):
    """Retrieve healing attempt timeline for an execution or plan."""
    query = db.query(HealingAttemptRecord)
    if exec_id.isdigit():
        heals = query.filter(HealingAttemptRecord.execution_id == int(exec_id)).order_by(HealingAttemptRecord.attempt_number.asc()).all()
    else:
        heals = query.filter(HealingAttemptRecord.plan_id == exec_id).order_by(HealingAttemptRecord.attempt_number.asc()).all()

    return [
        HealingAttemptResponse(
            id=h.id,
            execution_id=h.execution_id,
            plan_id=h.plan_id,
            attempt_number=h.attempt_number,
            error_signature=h.error_signature,
            error_class=h.error_class,
            error_message=h.error_message,
            remediation_class=h.remediation_class,
            fix_type=h.fix_type,
            root_cause=h.root_cause,
            reasoning=h.reasoning,
            confidence=h.confidence if h.confidence is not None else 1.0,
            risk_assessment=h.risk_assessment or "low",
            patch_data=json.loads(h.patch_data) if h.patch_data else None,
            diff=json.loads(h.diff) if h.diff else None,
            status=h.status,
            is_auto_applied=h.is_auto_applied or False,
            created_at=h.created_at.isoformat() if h.created_at else "",
            updated_at=h.updated_at.isoformat() if h.updated_at else None,
        )
        for h in heals
    ]


@app.post("/api/executions/{exec_id}/heals/{n}/approve", response_model=Dict[str, Any])
def approve_healing_attempt(exec_id: str, n: int, db: Session = Depends(get_db)):
    """Human approves healing attempt n."""
    query = db.query(HealingAttemptRecord)
    if exec_id.isdigit():
        attempt = query.filter(HealingAttemptRecord.execution_id == int(exec_id), HealingAttemptRecord.attempt_number == n).first()
    else:
        attempt = query.filter(HealingAttemptRecord.plan_id == exec_id, HealingAttemptRecord.attempt_number == n).first()

    if not attempt:
        attempt = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.id == n).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Healing attempt not found")

    updated = self_healing_engine.approve_heal(attempt_id=attempt.id, db=db)
    exec_res = orchestrator.execute_approved_plan(plan_id=attempt.plan_id, db=db)

    return {
        "status": "approved",
        "attempt_id": updated.id,
        "plan_id": updated.plan_id,
        "execution_result": exec_res.model_dump(),
    }


@app.post("/api/executions/{exec_id}/heals/{n}/reject", response_model=Dict[str, Any])
def reject_healing_attempt(exec_id: str, n: int, db: Session = Depends(get_db)):
    """Human rejects healing attempt n."""
    query = db.query(HealingAttemptRecord)
    if exec_id.isdigit():
        attempt = query.filter(HealingAttemptRecord.execution_id == int(exec_id), HealingAttemptRecord.attempt_number == n).first()
    else:
        attempt = query.filter(HealingAttemptRecord.plan_id == exec_id, HealingAttemptRecord.attempt_number == n).first()

    if not attempt:
        attempt = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.id == n).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Healing attempt not found")

    updated = self_healing_engine.reject_heal(attempt_id=attempt.id, db=db)
    return {
        "status": "rejected",
        "attempt_id": updated.id,
        "plan_id": updated.plan_id,
        "message": "Heal proposal rejected by operator.",
    }


@app.get("/api/remediations", response_model=List[RemediationKBItem])
def list_remediations(db: Session = Depends(get_db)):
    """List all Remediation KB entries."""
    records = kb_manager.list_all(db=db)
    return [
        RemediationKBItem(
            id=r.id,
            signature=r.signature,
            error_class=r.error_class,
            fix_type=r.fix_type,
            fix_template=json.loads(r.fix_template) if r.fix_template else None,
            description=r.description,
            success_count=r.success_count,
            failure_count=r.failure_count,
            cross_plan_failures=r.cross_plan_failures,
            enabled=r.enabled,
            is_promoted=r.is_promoted,
            circuit_broken=r.circuit_broken,
            version=r.version,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in records
    ]


@app.patch("/api/remediations/{rec_id}", response_model=RemediationKBItem)
def update_remediation(rec_id: int, req: RemediationKBUpdateRequest, db: Session = Depends(get_db)):
    """Update a Remediation KB entry (toggle enabled, edit description)."""
    rec = kb_manager.update_record(
        rec_id=rec_id,
        enabled=req.enabled,
        description=req.description,
        db=db,
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Remediation KB entry not found")

    return RemediationKBItem(
        id=rec.id,
        signature=rec.signature,
        error_class=rec.error_class,
        fix_type=rec.fix_type,
        fix_template=json.loads(rec.fix_template) if rec.fix_template else None,
        description=rec.description,
        success_count=rec.success_count,
        failure_count=rec.failure_count,
        cross_plan_failures=rec.cross_plan_failures,
        enabled=rec.enabled,
        is_promoted=rec.is_promoted,
        circuit_broken=rec.circuit_broken,
        version=rec.version,
        created_at=rec.created_at.isoformat() if rec.created_at else "",
        updated_at=rec.updated_at.isoformat() if rec.updated_at else None,
    )


# WebSocket for Live Terminal Logs
@app.websocket("/ws/execution/{plan_id}")
async def websocket_execution(websocket: WebSocket, plan_id: str):
    await websocket.accept()

    query_params = dict(websocket.query_params)
    reexecute = query_params.get("reexecute", "false").lower() in ["true", "1", "yes"]

    db = SessionLocal()
    try:
        plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
        if not plan:
            await websocket.send_text(f"__ERROR__Plan not found: {plan_id}")
            await websocket.close()
            return

        if reexecute:
            plan.status = "approved"
            db.commit()
            audit_logger.log(
                event_type="REEXEC_APPROVED",
                plan_id=plan_id,
                risk_level=plan.risk_level,
                action_by="human_operator",
                details={"action": "ws_reexecute"},
                db=db,
            )
        elif plan.status in ["completed", "failed", "partial_failed", "halted"]:
            exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).order_by(ExecutionRecord.id.desc()).first()
            if exec_rec and exec_rec.terraform_output:
                for line in exec_rec.terraform_output.splitlines():
                    await websocket.send_text(line)
            res = {
                "plan_id": plan_id,
                "status": plan.status,
                "success": exec_rec.success if exec_rec else (plan.status == "completed"),
                "run_number": exec_rec.run_number if exec_rec else 1,
                "resources_created": exec_rec.resources_created if exec_rec else 0,
                "resources_updated": exec_rec.resources_updated if exec_rec else 0,
                "resources_deleted": exec_rec.resources_deleted if exec_rec else 0,
                "terraform_output": exec_rec.terraform_output if exec_rec else "",
                "error_message": exec_rec.error_message if exec_rec else None,
                "execution_time_seconds": exec_rec.duration_seconds if exec_rec else 0.0,
            }
            if plan.status == "completed":
                await websocket.send_text(f"__COMPLETED__{json.dumps(res)}")
            else:
                err_msg = exec_rec.error_message if (exec_rec and exec_rec.error_message) else f"Execution ended in status '{plan.status}'"
                await websocket.send_text(f"__ERROR__{err_msg}")
            await websocket.close()
            return

        if settings.HUMAN_APPROVAL_REQUIRED and plan.status not in ["approved", "awaiting_approval", "executing"]:
            await websocket.send_text(f"__ERROR__Plan cannot be executed in current status: '{plan.status}'")
            await websocket.close()
            return
    finally:
        db.close()

    queue = asyncio.Queue()

    def live_logger(msg: str):
        queue.put_nowait(msg)

    def live_event(evt: dict):
        queue.put_nowait(f"__HEAL__{json.dumps(evt)}")

    async def sender():
        try:
            while True:
                msg = await queue.get()
                await websocket.send_text(msg)
        except asyncio.CancelledError:
            pass

    sender_task = asyncio.create_task(sender())
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: orchestrator.execute_approved_plan(
                plan_id=plan_id,
                on_log=live_logger,
                on_event=live_event,
            ),
        )
        while not queue.empty():
            msg = queue.get_nowait()
            await websocket.send_text(msg)
        await websocket.send_text(f"__COMPLETED__{json.dumps(result.model_dump())}")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_text(f"__ERROR__{str(e)}")
    finally:
        sender_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass



# ========================================================
# M-15: Environment Introspection & Conflict Prevention
# ========================================================

@app.get("/api/environment/snapshot")
def get_environment_snapshot(
    provider: str = "aws",
    region: str = "us-east-1",
    environment: Optional[str] = None,
    force_rescan: bool = False,
    db: Session = Depends(get_db)
):
    """Retrieve environment snapshot (M-15)."""
    if not environment or not str(environment).strip():
        raise HTTPException(
            status_code=400,
            detail="Target environment is missing. Please select an environment (e.g., LocalStack or an AWS connection).",
        )
    snap = environment_inventory.get_snapshot(provider=provider, region=region, environment=environment, force_rescan=force_rescan, db=db)
    return {
        "snapshot_id": snap.snapshot_id,
        "snapshot_hash": snap.snapshot_hash,
        "provider": snap.provider,
        "region": snap.region,
        "timestamp": snap.timestamp,
        "age_seconds": round(time.time() - snap.timestamp, 2),
        "is_stale": snap.is_stale(60.0),
        "counts": {
            "buckets": len(snap.buckets),
            "vpcs": len(snap.vpcs),
            "subnets": len(snap.subnets),
            "security_groups": len(snap.security_groups),
            "rds_instances": len(snap.rds_instances),
            "iam_roles": len(snap.iam_roles),
            "managed_resources": sum(len(v) for v in snap.managed_resources.values()),
        },
        "buckets": snap.buckets,
        "vpcs": snap.vpcs,
        "subnets": snap.subnets,
        "security_groups": snap.security_groups,
        "rds_instances": snap.rds_instances,
        "iam_roles": snap.iam_roles,
    }


@app.post("/api/environment/rescan")
def rescan_environment(
    provider: str = "aws",
    region: str = "us-east-1",
    environment: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Force an immediate parallel pre-flight scan of target environment (M-15)."""
    if not environment or not str(environment).strip():
        raise HTTPException(
            status_code=400,
            detail="Target environment is missing. Please select an environment (e.g., LocalStack or an AWS connection).",
        )
    snap = environment_inventory.get_snapshot(provider=provider, region=region, environment=environment, force_rescan=True, db=db)
    return {
        "status": "rescanned",
        "snapshot_id": snap.snapshot_id,
        "snapshot_hash": snap.snapshot_hash,
        "provider": snap.provider,
        "region": snap.region,
        "timestamp": snap.timestamp,
        "counts": {
            "buckets": len(snap.buckets),
            "vpcs": len(snap.vpcs),
            "subnets": len(snap.subnets),
            "security_groups": len(snap.security_groups),
            "rds_instances": len(snap.rds_instances),
            "iam_roles": len(snap.iam_roles),
            "managed_resources": sum(len(v) for v in snap.managed_resources.values()),
        },
    }


# ========================================================
# M-17: Connection Credentials UI & Service Scope Endpoints
# ========================================================

@app.get("/api/connections", response_model=List[ConnectionResponse])
def list_connections(db: Session = Depends(get_db)):
    """List all cloud connections. Zero secrets or unmasked key material are ever returned."""
    return credential_manager.list_connections(db)


@app.post("/api/connections", response_model=ConnectionResponse)
def create_connection(payload: ConnectionCreateRequest, db: Session = Depends(get_db)):
    """Create a new cloud connection with encrypted credentials at rest."""
    try:
        created = credential_manager.create_connection(
            db=db,
            name=payload.name,
            provider=payload.provider,
            environment=payload.environment,
            auth_method=payload.auth_method,
            region=payload.region,
            access_key_id=payload.access_key_id,
            secret_access_key=payload.secret_access_key,
            services=payload.services,
            profile_name=payload.profile_name,
            confirm_name=payload.confirm_name,
        )
        return created
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/connections/{connection_id}", response_model=ConnectionResponse)
def get_connection(connection_id: str, db: Session = Depends(get_db)):
    """Retrieve connection details (masked credentials only)."""
    conn = credential_manager.get_connection(connection_id, db)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@app.patch("/api/connections/{connection_id}", response_model=ConnectionResponse)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update connection settings. Blank secret keeps existing stored secret."""
    try:
        updated = credential_manager.update_connection(
            db=db,
            connection_id=connection_id,
            name=payload.name,
            provider=payload.provider,
            environment=payload.environment,
            auth_method=payload.auth_method,
            region=payload.region,
            access_key_id=payload.access_key_id,
            secret_access_key=payload.secret_access_key,
            services=payload.services,
            profile_name=payload.profile_name,
            confirm_name=payload.confirm_name,
            acknowledge=payload.acknowledge or False,
        )
        return updated
    except ValueError as e:
        err_msg = str(e)
        if "Existing managed resources use services being removed" in err_msg:
            raise HTTPException(status_code=409, detail=err_msg)
        raise HTTPException(status_code=422, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/connections/{connection_id}")
def delete_connection(connection_id: str, db: Session = Depends(get_db)):
    """Purge credentials ciphertext immediately, mark deleted, and audit."""
    try:
        return credential_manager.delete_connection(db, connection_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/connections/{connection_id}/test", response_model=ConnectionTestResponse)
def test_connection_by_id(connection_id: str, db: Session = Depends(get_db)):
    """Run STS caller identity probe and per-service read-only checks on a saved connection."""
    try:
        return credential_manager.test_connection_by_id(connection_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Probe failed: {str(e)}")


@app.post("/api/connections/test", response_model=ConnectionTestResponse)
def test_unsaved_connection(payload: ConnectionCreateRequest):
    """Run STS and per-service read-only probes for unsaved form values before saving in drawer."""
    try:
        return credential_manager.probe_connection(
            provider=payload.provider,
            environment=payload.environment,
            region=payload.region,
            access_key=payload.access_key_id,
            secret_key=payload.secret_access_key,
            services=payload.services,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Probe failed: {str(e)}")


@app.post("/api/connections/{connection_id}/services")
def update_connection_services(
    connection_id: str,
    payload: ServicesUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update connection services scope list."""
    try:
        return credential_manager.update_services(
            db=db,
            connection_id=connection_id,
            services=payload.services,
            acknowledge=payload.acknowledge,
        )
    except ValueError as e:
        err_msg = str(e)
        if "Existing managed resources use services being removed" in err_msg:
            raise HTTPException(status_code=409, detail=err_msg)
        raise HTTPException(status_code=422, detail=err_msg)


@app.post("/api/localstack/restart", response_model=LocalStackRestartResponse)
def restart_localstack(db: Session = Depends(get_db)):
    """Apply new services list and restart LocalStack container, polling health until ready."""
    return credential_manager.restart_localstack(db)


# Serve Built Frontend SPA if available
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

frontend_dist = Path("frontend/dist")
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")

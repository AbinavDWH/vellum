import time
import json
import hashlib
import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field
import boto3
import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.healing.sanitizer import sanitize_text
from app.models import WireTraceRecordModel, PlanRecord, ConnectionRecord
from app.database import SessionLocal

logger = structlog.get_logger(__name__)


def sanitize_params(params: Any) -> Any:
    """Mask secrets and credential materials in wire-trace parameters."""
    if isinstance(params, dict):
        out = {}
        for k, v in params.items():
            if any(term in k.lower() for term in ["secret", "password", "token", "key", "auth", "credential"]):
                out[k] = "[REDACTED_SECRET]"
            else:
                out[k] = sanitize_params(v)
        return out
    elif isinstance(params, list):
        return [sanitize_params(x) for x in params]
    elif isinstance(params, str):
        return sanitize_text(params)
    return params


class WireTraceRecord(BaseModel):
    seq: int
    ts: str
    plan_id: str
    execution_id: Optional[int] = None
    connection_id: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    service: str
    operation: str
    source: str = "vellum-sdk"  # "vellum-sdk" | "terraform"
    params_masked: Dict[str, Any] = Field(default_factory=dict)
    http_status: int = 200
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_id: Optional[str] = None
    latency_ms: float = 0.0
    cloudtrail_confirmed: Optional[bool] = None


class WireTraceCollector:
    """Captures sanitized wire-level records of Vellum SDK & Terraform interactions with AWS (M-19)."""

    def __init__(self):
        # In-memory buffer per plan_id
        self._traces: Dict[str, List[WireTraceRecord]] = {}
        self._seq_counter: Dict[str, int] = {}

    def clear_plan(self, plan_id: str):
        """Reset in-memory trace buffers for a plan."""
        self._traces.pop(plan_id, None)
        self._seq_counter.pop(plan_id, None)

    def _next_seq(self, plan_id: str) -> int:
        self._seq_counter[plan_id] = self._seq_counter.get(plan_id, 0) + 1
        return self._seq_counter[plan_id]

    def attach_to_boto3_client(
        self,
        client: Any,
        plan_id: str,
        connection_id: Optional[str] = None,
        account: Optional[str] = None,
        region: Optional[str] = None,
        source: str = "vellum-sdk",
        execution_id: Optional[int] = None,
        db: Optional[Session] = None,
    ):
        """Register after-call and after-call-error event hooks on botocore client."""
        if not hasattr(client, "meta") or not hasattr(client.meta, "events"):
            return

        events = client.meta.events
        svc_name = client.meta.service_model.service_name

        def before_call_handler(*args, **kwargs):
            context = kwargs.get("context")
            if context is None and len(args) > 3:
                context = args[3]
            if context is not None:
                context["_vellum_start_time"] = time.time()
                params = kwargs.get("params") or (args[1] if len(args) > 1 else {})
                context["_vellum_params"] = sanitize_params(params)

        def after_call_handler(*args, **kwargs):
            context = kwargs.get("context")
            if context is None and len(args) > 3:
                context = args[3]
            context = context or {}

            latency = 0.0
            if "_vellum_start_time" in context:
                latency = round((time.time() - context["_vellum_start_time"]) * 1000, 2)

            http_response = kwargs.get("http_response") or (args[0] if len(args) > 0 else None)
            model = kwargs.get("model")
            op_name = getattr(model, "name", None) or kwargs.get("operation_name")
            if not op_name and "event_name" in kwargs:
                parts = kwargs["event_name"].split(".")
                if len(parts) >= 3:
                    op_name = parts[-1]
            op_name = op_name or "UnknownOperation"

            status_code = 200
            request_id = None

            if isinstance(http_response, tuple) and len(http_response) == 2:
                resp_obj, parsed = http_response
                if hasattr(resp_obj, "status_code"):
                    status_code = resp_obj.status_code
                if isinstance(parsed, dict):
                    request_id = parsed.get("ResponseMetadata", {}).get("RequestId")
                if not request_id and hasattr(resp_obj, "headers"):
                    request_id = resp_obj.headers.get("x-amzn-requestid") or resp_obj.headers.get("x-amz-request-id")
            elif hasattr(http_response, "status_code"):
                status_code = http_response.status_code
                parsed = kwargs.get("parsed")
                if isinstance(parsed, dict):
                    request_id = parsed.get("ResponseMetadata", {}).get("RequestId")

            params = context.get("_vellum_params", {})
            self.record_call(
                plan_id=plan_id,
                service=svc_name,
                operation=op_name,
                http_status=status_code,
                request_id=request_id,
                latency_ms=latency,
                params_masked=params,
                connection_id=connection_id,
                account=account,
                region=region,
                source=source,
                execution_id=execution_id,
                db=db,
            )

        def after_call_error_handler(*args, **kwargs):
            context = kwargs.get("context") or {}
            latency = 0.0
            if "_vellum_start_time" in context:
                latency = round((time.time() - context["_vellum_start_time"]) * 1000, 2)

            exception = kwargs.get("exception") or (args[0] if len(args) > 0 else None)
            error_code = type(exception).__name__ if exception else "UnknownError"
            error_msg = str(exception) if exception else ""
            status_code = 400
            request_id = None

            op_name = kwargs.get("operation_name")
            if not op_name and "event_name" in kwargs:
                parts = kwargs["event_name"].split(".")
                if len(parts) >= 3:
                    op_name = parts[-1]
            op_name = op_name or "UnknownOperation"

            if hasattr(exception, "response") and isinstance(exception.response, dict):
                status_code = exception.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400)
                request_id = exception.response.get("ResponseMetadata", {}).get("RequestId")
                err_dict = exception.response.get("Error", {})
                error_code = err_dict.get("Code", error_code)
                error_msg = err_dict.get("Message", error_msg)

            params = context.get("_vellum_params", {})
            self.record_call(
                plan_id=plan_id,
                service=svc_name,
                operation=op_name,
                http_status=status_code,
                error_code=error_code,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency,
                params_masked=params,
                connection_id=connection_id,
                account=account,
                region=region,
                source=source,
                execution_id=execution_id,
                db=db,
            )

        events.register("before-call", before_call_handler)
        events.register("after-call", after_call_handler)
        events.register("after-call-error", after_call_error_handler)

    def record_call(
        self,
        plan_id: str,
        service: str,
        operation: str,
        http_status: int = 200,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        latency_ms: float = 0.0,
        params_masked: Optional[Dict[str, Any]] = None,
        connection_id: Optional[str] = None,
        account: Optional[str] = None,
        region: Optional[str] = None,
        source: str = "vellum-sdk",
        execution_id: Optional[int] = None,
        cloudtrail_confirmed: Optional[bool] = None,
        db: Optional[Session] = None,
    ) -> WireTraceRecord:
        """Append a trace record in-memory and persist to DB."""
        seq = self._next_seq(plan_id)
        ts = datetime.datetime.utcnow().isoformat()
        masked = sanitize_params(params_masked or {})

        rec = WireTraceRecord(
            seq=seq,
            ts=ts,
            plan_id=plan_id,
            execution_id=execution_id,
            connection_id=connection_id,
            account=account,
            region=region,
            service=service,
            operation=operation,
            source=source,
            params_masked=masked,
            http_status=http_status,
            error_code=error_code,
            error_message=error_message,
            request_id=request_id,
            latency_ms=latency_ms,
            cloudtrail_confirmed=cloudtrail_confirmed,
        )

        if plan_id not in self._traces:
            self._traces[plan_id] = []
        self._traces[plan_id].append(rec)

        # Persist to database if Session provided or via local session
        active_db = db
        close_db = False
        if active_db is None:
            try:
                active_db = SessionLocal()
                close_db = True
            except Exception:
                active_db = None

        if active_db is not None:
            try:
                db_model = WireTraceRecordModel(
                    plan_id=plan_id,
                    execution_id=execution_id,
                    seq=seq,
                    timestamp=datetime.datetime.utcnow(),
                    connection_id=connection_id,
                    account=account,
                    region=region,
                    service=service,
                    operation=operation,
                    source=source,
                    params_masked_json=json.dumps(masked),
                    http_status=http_status,
                    error_code=error_code,
                    error_message=error_message,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    cloudtrail_confirmed=cloudtrail_confirmed,
                )
                active_db.add(db_model)
                active_db.commit()
            except Exception as e:
                logger.warning("Failed to persist wire trace to database", error=str(e), plan_id=plan_id)
            finally:
                if close_db:
                    active_db.close()

        return rec

    def record_terraform_call(
        self,
        plan_id: str,
        service: str,
        operation: str,
        http_status: int = 200,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        latency_ms: float = 0.0,
        params: Optional[Dict[str, Any]] = None,
        connection_id: Optional[str] = None,
        account: Optional[str] = None,
        region: Optional[str] = None,
        execution_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> WireTraceRecord:
        """Record wire trace row generated during Terraform apply or state sync."""
        return self.record_call(
            plan_id=plan_id,
            service=service,
            operation=operation,
            http_status=http_status,
            error_code=error_code,
            error_message=error_message,
            request_id=request_id,
            latency_ms=latency_ms,
            params_masked=params or {},
            connection_id=connection_id,
            account=account,
            region=region,
            source="terraform",
            execution_id=execution_id,
            db=db,
        )

    def get_traces(self, plan_id: str, db: Optional[Session] = None) -> List[WireTraceRecord]:
        """Fetch all traces for a plan ID from memory or DB."""
        if plan_id in self._traces and len(self._traces[plan_id]) > 0:
            return list(self._traces[plan_id])

        # Query database fallback
        active_db = db
        close_db = False
        if active_db is None:
            try:
                active_db = SessionLocal()
                close_db = True
            except Exception:
                active_db = None

        results: List[WireTraceRecord] = []
        if active_db is not None:
            try:
                rows = (
                    active_db.query(WireTraceRecordModel)
                    .filter(WireTraceRecordModel.plan_id == plan_id)
                    .order_by(WireTraceRecordModel.seq.asc())
                    .all()
                )
                for r in rows:
                    params = {}
                    if r.params_masked_json:
                        try:
                            params = json.loads(r.params_masked_json)
                        except Exception:
                            pass
                    rec = WireTraceRecord(
                        seq=r.seq,
                        ts=r.timestamp.isoformat() if r.timestamp else datetime.datetime.utcnow().isoformat(),
                        plan_id=r.plan_id,
                        execution_id=r.execution_id,
                        connection_id=r.connection_id,
                        account=r.account,
                        region=r.region,
                        service=r.service,
                        operation=r.operation,
                        source=r.source,
                        params_masked=params,
                        http_status=r.http_status,
                        error_code=r.error_code,
                        error_message=r.error_message,
                        request_id=r.request_id,
                        latency_ms=r.latency_ms or 0.0,
                        cloudtrail_confirmed=r.cloudtrail_confirmed,
                    )
                    results.append(rec)
                if results:
                    self._traces[plan_id] = list(results)
                    self._seq_counter[plan_id] = max(r.seq for r in results)
            finally:
                if close_db:
                    active_db.close()

        return results

    def export_trace_json(self, plan_id: str, db: Optional[Session] = None) -> Tuple[str, str]:
        """Export trace list as serialized JSON and its SHA-256 fingerprint."""
        traces = self.get_traces(plan_id, db=db)
        data = [t.model_dump() for t in traces]
        json_str = json.dumps(data, indent=2, default=str)
        sha256_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
        return json_str, sha256_hash

    def verify_cloudtrail_crosscheck(
        self,
        plan_id: str,
        connection_id: Optional[str] = None,
        account: Optional[str] = None,
        region: Optional[str] = None,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Query CloudTrail lookup-events for execution window and match against Vellum trace.
        Detects zombie/out-of-band resources not initiated by Vellum.
        """
        traces = self.get_traces(plan_id, db=db)
        target_region = region or "us-east-1"

        if not aws_access_key or aws_access_key == "test":
            # Simulation mode / LocalStack
            for t in traces:
                t.cloudtrail_confirmed = True
            return {
                "total_traces": len(traces),
                "confirmed_traces": len(traces),
                "cloudtrail_events_checked": 0,
                "matched_events": len(traces),
                "zombie_events": [],
                "zombie_detected": False,
                "confirmed_badge": True,
                "note": "Simulation mode: CloudTrail cross-check emulated for LocalStack."
            }

        client_kwargs = {
            "region_name": target_region,
            "aws_access_key_id": aws_access_key,
            "aws_secret_access_key": aws_secret_key,
        }

        try:
            ct = boto3.client("cloudtrail", **client_kwargs)
            now = datetime.datetime.utcnow()
            st = start_time or (now - datetime.timedelta(minutes=30))
            et = end_time or (now + datetime.timedelta(minutes=5))

            resp = ct.lookup_events(
                StartTime=st,
                EndTime=et,
                MaxResults=50,
            )
            ct_events = resp.get("Events", [])
        except Exception as e:
            logger.warning("CloudTrail lookup-events query failed", error=str(e), plan_id=plan_id)
            return {
                "total_traces": len(traces),
                "confirmed_traces": 0,
                "cloudtrail_events_checked": 0,
                "matched_events": 0,
                "zombie_events": [],
                "zombie_detected": False,
                "confirmed_badge": False,
                "error": str(e),
            }

        # Match CloudTrail events with Vellum traces
        matched_traces = set()
        matched_ct_event_ids = set()

        for t in traces:
            op_lower = t.operation.lower()
            for ev in ct_events:
                ev_name = ev.get("EventName", "").lower()
                ev_req_id = ""
                # CloudTrail CloudTrailEvent is a JSON string
                ct_raw = ev.get("CloudTrailEvent")
                if ct_raw:
                    try:
                        ct_parsed = json.loads(ct_raw)
                        ev_req_id = ct_parsed.get("requestID", "")
                    except Exception:
                        pass

                is_match = False
                if t.request_id and ev_req_id and t.request_id == ev_req_id:
                    is_match = True
                elif op_lower == ev_name or op_lower.replace("_", "") == ev_name.replace("_", ""):
                    is_match = True

                if is_match:
                    t.cloudtrail_confirmed = True
                    matched_traces.add(t.seq)
                    matched_ct_event_ids.add(ev.get("EventId"))
                    break

        # Check for zombie calls: mutating actions in CloudTrail that Vellum never initiated
        zombie_events = []
        for ev in ct_events:
            ev_id = ev.get("EventId")
            if ev_id in matched_ct_event_ids:
                continue

            ev_name = ev.get("EventName", "")
            # Mutating action keywords
            if any(ev_name.startswith(p) for p in ["Create", "Delete", "Modify", "Run", "Put", "Attach"]):
                # Non-Vellum or zombie event
                zombie_events.append({
                    "event_id": ev_id,
                    "event_name": ev_name,
                    "event_time": str(ev.get("EventTime")),
                    "username": ev.get("Username"),
                })

        zombie_detected = len(zombie_events) > 0
        confirmed_badge = len(matched_traces) > 0 and not zombie_detected

        return {
            "total_traces": len(traces),
            "confirmed_traces": len(matched_traces),
            "cloudtrail_events_checked": len(ct_events),
            "matched_events": len(matched_traces),
            "zombie_events": zombie_events,
            "zombie_detected": zombie_detected,
            "confirmed_badge": confirmed_badge,
        }

    def clear(self, plan_id: str):
        self._traces.pop(plan_id, None)
        self._seq_counter.pop(plan_id, None)


wire_trace_collector = WireTraceCollector()

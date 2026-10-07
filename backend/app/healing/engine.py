import json
import datetime
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.models import ExecutionRecord, HealingAttemptRecord, PlanRecord, RemediationKBRecord
from app.database import SessionLocal
from app.schemas.ir import UniversalIR
from app.audit.logger import audit_logger
from app.healing.detector import error_detector, DetectedError
from app.healing.matrix import remediation_matrix
from app.healing.sanitizer import sanitize_logs
from app.healing.proposer import llm_fix_proposer, LLMFixProposal
from app.healing.validator import fix_validator, FixValidationResult
from app.healing.playbooks import playbooks
from app.healing.kb import kb_manager

logger = structlog.get_logger(__name__)


class SelfHealingEngine:
    """Core autonomous self-healing execution engine (M-14)."""

    MAX_HEALING_ATTEMPTS = 3

    def __init__(self):
        pass

    def evaluate_and_heal(
        self,
        plan_id: str,
        execution_id: Optional[int],
        attempt_number: int,
        log_text: str,
        current_ir: UniversalIR,
        plan_dir: str,
        on_log: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        db: Optional[Session] = None,
    ) -> Tuple[bool, Optional[UniversalIR], Optional[str], Optional[DetectedError], Optional[HealingAttemptRecord]]:
        """
        Executes one healing loop iteration:
        Returns:
            (should_reexecute, updated_ir, updated_hcl, detected_error, healing_record)
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            # 1. Error Detection (deterministic signatures, not LLM)
            detected = error_detector.detect(log_text)
            if not detected:
                # No error detected
                return False, None, None, None, None

            # Log tap notification
            if on_log:
                on_log(f"🔍 [HEAL] Error signature detected: [{detected.signature}] (Class: {detected.error_class.upper()}, Attempt {attempt_number}/{self.MAX_HEALING_ATTEMPTS})")

            # Audit: HEAL_DETECTED
            audit_logger.log(
                event_type="HEAL_DETECTED",
                plan_id=plan_id,
                risk_level="medium" if not detected.is_unfixable else "high",
                action_by="self_healing_engine",
                details={
                    "signature": detected.signature,
                    "error_class": detected.error_class,
                    "attempt": attempt_number,
                    "excerpt": detected.raw_excerpt[:200],
                },
                db=db,
            )

            # Emit WS event: heal_detected
            self._emit_event(on_event, {
                "event": "heal_detected",
                "signature": detected.signature,
                "error_class": detected.error_class,
                "attempt": attempt_number,
                "max_attempts": self.MAX_HEALING_ATTEMPTS,
                "message": detected.message,
                "remediation_class": detected.remediation_class,
            })

            # 2. Check Loop Cap (max 3 attempts per execution)
            if attempt_number > self.MAX_HEALING_ATTEMPTS:
                msg = f"Healing loop cap reached ({self.MAX_HEALING_ATTEMPTS} attempts exhausted). Halting execution to avoid infinite loops."
                if on_log:
                    on_log(f"🛑 [HEAL] {msg}")

                heal_rec = self._create_healing_record(
                    db=db,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    attempt_number=attempt_number,
                    detected=detected,
                    status="halted",
                    root_cause="Max healing attempts reached",
                    reasoning=msg,
                    diff={"error": msg},
                )

                audit_logger.log(
                    event_type="HEAL_HALTED",
                    plan_id=plan_id,
                    risk_level="high",
                    action_by="self_healing_engine",
                    details={"reason": "loop_cap_reached", "attempts": attempt_number},
                    db=db,
                )
                self._emit_event(on_event, {
                    "event": "heal_halted",
                    "signature": detected.signature,
                    "attempt": attempt_number,
                    "reason": "loop_cap_reached",
                    "diagnosis": detected.diagnosis or msg,
                })
                return False, None, None, detected, heal_rec

            # 3. Check UNFIXABLE CLASS (Auth, Quota, Runtime)
            if detected.is_unfixable or detected.error_class in ["auth", "quota", "runtime"]:
                diag = detected.diagnosis or "Unfixable error class detected. Automatic remediation blocked."
                if on_log:
                    on_log(f"🚫 [HEAL] Unfixable class [{detected.error_class.upper()}]. Zero auto-actions allowed.")
                    on_log(f"ℹ️ [HEAL] Diagnosis: {diag}")

                heal_rec = self._create_healing_record(
                    db=db,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    attempt_number=attempt_number,
                    detected=detected,
                    status="halted",
                    remediation_class="halted",
                    root_cause=f"Unfixable {detected.error_class} error",
                    reasoning=diag,
                    diff={"action": "halt", "diagnosis": diag},
                )

                audit_logger.log(
                    event_type="HEAL_HALTED",
                    plan_id=plan_id,
                    risk_level="critical",
                    action_by="self_healing_engine",
                    details={
                        "signature": detected.signature,
                        "error_class": detected.error_class,
                        "diagnosis": diag,
                    },
                    db=db,
                )
                self._emit_event(on_event, {
                    "event": "heal_halted",
                    "signature": detected.signature,
                    "error_class": detected.error_class,
                    "attempt": attempt_number,
                    "diagnosis": diag,
                })
                return False, None, None, detected, heal_rec

            # 4. Check Circuit Breaker & KB record
            kb_rec = kb_manager.get_kb_record(detected.signature, db=db)
            circuit_broken = kb_rec.circuit_broken if kb_rec else False
            is_promoted = kb_rec.is_promoted if kb_rec else False

            if circuit_broken or (kb_rec and not kb_rec.enabled):
                alert_msg = f"Circuit breaker active for playbook [{detected.signature}]. Automatic remediation is temporarily disabled."
                if on_log:
                    on_log(f"⚠️ [HEAL] {alert_msg}")

                heal_rec = self._create_healing_record(
                    db=db,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    attempt_number=attempt_number,
                    detected=detected,
                    status="awaiting_approval",
                    remediation_class="approve",
                    root_cause="Circuit breaker tripped",
                    reasoning=alert_msg,
                    diff={"circuit_broken": True},
                )
                self._emit_event(on_event, {
                    "event": "heal_proposed",
                    "signature": detected.signature,
                    "attempt": attempt_number,
                    "status": "awaiting_approval",
                    "reasoning": alert_msg,
                })
                return False, None, None, detected, heal_rec

            # 5. Check if Deterministic Playbook Hit (Promoted or Native Matrix)
            auto_allowed, rem_class, max_allowed = remediation_matrix.evaluate(
                detected=detected,
                circuit_broken=circuit_broken,
                is_promoted=is_promoted,
            )

            # If promoted or known playbook in native auto-whitelist
            is_native_playbook = detected.signature in [
                "BucketAlreadyExists",
                "InvalidSubnet.Range",
                "ResourceNotFound",
                "HCLSyntaxError",
                "SQLSyntaxError",
                "ConnectionRefused",
            ]

            if (auto_allowed and is_native_playbook) or (is_promoted and not circuit_broken and kb_rec and kb_rec.enabled):
                return self._apply_deterministic_playbook(
                    detected=detected,
                    current_ir=current_ir,
                    plan_dir=plan_dir,
                    plan_id=plan_id,
                    execution_id=execution_id,
                    attempt_number=attempt_number,
                    on_log=on_log,
                    on_event=on_event,
                    db=db,
                    kb_rec=kb_rec,
                )

            # 6. Unknown Error or Requires LLM Proposal
            return self._propose_and_validate_llm_fix(
                detected=detected,
                log_text=log_text,
                current_ir=current_ir,
                plan_dir=plan_dir,
                plan_id=plan_id,
                execution_id=execution_id,
                attempt_number=attempt_number,
                on_log=on_log,
                on_event=on_event,
                db=db,
            )

        finally:
            if close_db:
                db.close()

    def _apply_deterministic_playbook(
        self,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
        plan_id: str,
        execution_id: Optional[int],
        attempt_number: int,
        on_log: Optional[Callable[[str], None]],
        on_event: Optional[Callable[[Dict[str, Any]], None]],
        db: Session,
        kb_rec: Optional[RemediationKBRecord] = None,
    ) -> Tuple[bool, Optional[UniversalIR], Optional[str], Optional[DetectedError], Optional[HealingAttemptRecord]]:
        """Applies a known, pre-validated deterministic playbook."""
        sig = detected.signature
        if on_log:
            on_log(f"⚙️ [HEAL] Executing deterministic playbook for [{sig}]...")

        success = False
        patched_ir = current_ir
        new_hcl = ""
        diff: Dict[str, Any] = {}

        if sig == "BucketAlreadyExists":
            success, patched_ir, new_hcl, diff = playbooks.apply_bucket_already_exists(detected, current_ir, plan_dir)
        elif sig == "InvalidSubnet.Range":
            success, patched_ir, new_hcl, diff = playbooks.apply_cidr_recompute(detected, current_ir, plan_dir)
        elif sig == "ResourceNotFound":
            success, patched_ir, new_hcl, diff = playbooks.apply_dependency_ordering(detected, current_ir, plan_dir)
        elif sig == "HCLSyntaxError":
            success, patched_ir, new_hcl, diff = playbooks.apply_regenerate_hcl(detected, current_ir, plan_dir)
        elif sig == "SQLSyntaxError":
            success, patched_ir, new_hcl, diff = playbooks.apply_regenerate_sql(detected, current_ir, plan_dir)
        elif sig == "ConnectionRefused":
            delay = playbooks.apply_transient_retry(attempt=attempt_number)
            success = True
            diff = {"action": "retry_backoff", "delay_seconds": delay}
        elif kb_rec and kb_rec.is_promoted and kb_rec.fix_template:
            try:
                template_patch = json.loads(kb_rec.fix_template)
                proposal = LLMFixProposal(
                    root_cause=kb_rec.description or f"Promoted fix for {sig}",
                    fix_type=kb_rec.fix_type,
                    patch=template_patch,
                    reasoning="Promoted deterministic playbook executed with zero LLM calls.",
                    confidence=1.0,
                    risk_assessment="low",
                )
                val_res = fix_validator.validate_proposal(proposal, current_ir, plan_dir, plan_id)
                if val_res.is_valid and not val_res.is_security_widened:
                    success = True
                    patched_ir = val_res.patched_ir or current_ir
                    new_hcl = val_res.patched_hcl or ""
                    diff = val_res.diff
            except Exception as e:
                logger.warning("Failed to apply promoted playbook template", signature=sig, error=str(e))
                success = False

        if success:
            # Audit: HEAL_PROPOSED & HEAL_APPLIED
            audit_logger.log(
                event_type="HEAL_PROPOSED",
                plan_id=plan_id,
                risk_level="low",
                action_by="self_healing_engine",
                details={"signature": sig, "diff": diff, "auto_allowed": True},
                db=db,
            )
            audit_logger.log(
                event_type="HEAL_APPLIED",
                plan_id=plan_id,
                risk_level="low",
                action_by="self_healing_engine",
                details={"signature": sig, "diff": diff, "attempt": attempt_number},
                db=db,
            )

            # Record healing attempt
            heal_rec = self._create_healing_record(
                db=db,
                execution_id=execution_id,
                plan_id=plan_id,
                attempt_number=attempt_number,
                detected=detected,
                status="applied",
                remediation_class="auto",
                fix_type=diff.get("action", "playbook"),
                root_cause=detected.diagnosis or f"Deterministic match for {sig}",
                reasoning=diff.get("reasoning", "Applied deterministic playbook."),
                diff=diff,
                is_auto_applied=True,
            )

            # Emit WS events
            self._emit_event(on_event, {
                "event": "heal_proposed",
                "signature": sig,
                "attempt": attempt_number,
                "status": "proposed",
                "diff": diff,
                "auto_applied": True,
            })
            self._emit_event(on_event, {
                "event": "heal_applied",
                "signature": sig,
                "attempt": attempt_number,
                "status": "applied",
                "diff": diff,
            })

            if on_log:
                on_log(f"✅ [HEAL] Fix successfully applied: {diff.get('reasoning', 'Playbook executed.')}")
                on_log(f"🔄 [HEAL] Re-executing apply (Attempt {attempt_number + 1})...")

            return True, patched_ir, new_hcl, detected, heal_rec

        return False, None, None, detected, None

    def _propose_and_validate_llm_fix(
        self,
        detected: DetectedError,
        log_text: str,
        current_ir: UniversalIR,
        plan_dir: str,
        plan_id: str,
        execution_id: Optional[int],
        attempt_number: int,
        on_log: Optional[Callable[[str], None]],
        on_event: Optional[Callable[[Dict[str, Any]], None]],
        db: Session,
    ) -> Tuple[bool, Optional[UniversalIR], Optional[str], Optional[DetectedError], Optional[HealingAttemptRecord]]:
        """Handles unknown or non-whitelisted errors via sanitized LLM Fix Proposer."""
        if on_log:
            on_log(f"🤖 [HEAL] Invoking LLM Fix Proposer with sanitized execution log...")

        # Read HCL excerpt
        main_tf_path = Path(plan_dir) / "main.tf"
        hcl_content = main_tf_path.read_text(encoding="utf-8") if main_tf_path.exists() else ""

        # Call proposer (contract: input sanitized, output validated)
        proposal: LLMFixProposal = llm_fix_proposer.propose_fix(
            error_signature=detected.signature,
            logs=log_text,
            current_ir=current_ir,
            hcl_excerpt=hcl_content,
            provider="aws",
        )

        if on_log:
            on_log(f"💡 [HEAL] LLM Diagnosis: {proposal.root_cause}")
            on_log(f"🔍 [HEAL] Validating proposal in sandbox workspace (policy & terraform validate)...")

        # Fix validation: schema -> policy -> sandbox dry-run
        val_res: FixValidationResult = fix_validator.validate_proposal(
            proposal=proposal,
            current_ir=current_ir,
            plan_dir=plan_dir,
            plan_id=plan_id,
        )

        # Audit: HEAL_PROPOSED
        audit_logger.log(
            event_type="HEAL_PROPOSED",
            plan_id=plan_id,
            risk_level=val_res.risk_level,
            action_by="llm_fix_proposer",
            details={
                "signature": detected.signature,
                "root_cause": proposal.root_cause,
                "reasoning": proposal.reasoning,
                "confidence": proposal.confidence,
                "diff": val_res.diff,
                "is_valid": val_res.is_valid,
                "risk_level": val_res.risk_level,
            },
            db=db,
        )

        # Determine if auto-apply is permissible
        # Rule: Low-risk whitelist and not security-widened and proposal valid
        kb_rec = kb_manager.get_kb_record(detected.signature, db=db)
        circuit_broken = kb_rec.circuit_broken if kb_rec else False
        is_promoted = kb_rec.is_promoted if kb_rec else False

        matrix_auto_allowed, _, _ = remediation_matrix.evaluate(
            detected=detected,
            is_destructive=val_res.is_destructive,
            is_security_widened=val_res.is_security_widened,
            circuit_broken=circuit_broken,
            is_promoted=is_promoted,
            risk_level=val_res.risk_level,
        )

        can_auto_apply = (
            matrix_auto_allowed
            and val_res.is_valid
            and not val_res.is_security_widened
            and not val_res.is_destructive
            and val_res.risk_level == "low"
            and proposal.confidence >= 0.80
        )

        if can_auto_apply:
            if on_log:
                on_log(f"⚡ [HEAL] Low-risk proposal verified. Auto-applying patch to plan workspace...")

            patched_ir = val_res.patched_ir or current_ir
            new_hcl = val_res.patched_hcl or ""

            # Update workspace main.tf if generated
            if new_hcl and main_tf_path.exists():
                main_tf_path.write_text(new_hcl, encoding="utf-8")

            # Update PlanRecord ir_json and terraform_code
            plan_rec = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
            if plan_rec:
                plan_rec.ir_json = patched_ir.model_dump_json()
                if new_hcl:
                    plan_rec.terraform_code = new_hcl
                db.commit()

            # Record success in Remediation KB learning loop
            promoted = kb_manager.record_success(
                signature=detected.signature,
                fix_type=proposal.fix_type,
                patch_template=proposal.patch,
                db=db,
            )
            if promoted and on_log:
                on_log(f"🏆 [HEAL] Playbook Promotion: [{detected.signature}] healed 3× successfully! Promoted to deterministic playbook.")

            # Audit: HEAL_APPLIED
            audit_logger.log(
                event_type="HEAL_APPLIED",
                plan_id=plan_id,
                risk_level=val_res.risk_level,
                action_by="self_healing_engine",
                details={
                    "signature": detected.signature,
                    "diff": val_res.diff,
                    "attempt": attempt_number,
                    "auto_applied": True,
                },
                db=db,
            )

            heal_rec = self._create_healing_record(
                db=db,
                execution_id=execution_id,
                plan_id=plan_id,
                attempt_number=attempt_number,
                detected=detected,
                status="applied",
                remediation_class="auto",
                fix_type=proposal.fix_type,
                root_cause=proposal.root_cause,
                reasoning=proposal.reasoning,
                confidence=proposal.confidence,
                risk_assessment=val_res.risk_level,
                patch_data=proposal.patch,
                diff=val_res.diff,
                is_auto_applied=True,
            )

            self._emit_event(on_event, {
                "event": "heal_proposed",
                "signature": detected.signature,
                "attempt": attempt_number,
                "status": "proposed",
                "diff": val_res.diff,
                "auto_applied": True,
                "reasoning": proposal.reasoning,
                "confidence": proposal.confidence,
            })
            self._emit_event(on_event, {
                "event": "heal_applied",
                "signature": detected.signature,
                "attempt": attempt_number,
                "status": "applied",
                "diff": val_res.diff,
            })

            if on_log:
                on_log(f"🔄 [HEAL] Re-executing apply with patched configuration (Attempt {attempt_number + 1})...")

            return True, patched_ir, new_hcl, detected, heal_rec

        else:
            # Human approval gate required
            if on_log:
                on_log(f"⚠️ [HEAL] Proposal requires human operator review. Risk level: {val_res.risk_level.upper()}.")
                on_log(f"ℹ️ [HEAL] Action needed: Approve or reject fix in Execution Console.")

            heal_rec = self._create_healing_record(
                db=db,
                execution_id=execution_id,
                plan_id=plan_id,
                attempt_number=attempt_number,
                detected=detected,
                status="awaiting_approval",
                remediation_class="approve",
                fix_type=proposal.fix_type,
                root_cause=proposal.root_cause,
                reasoning=proposal.reasoning,
                confidence=proposal.confidence,
                risk_assessment=val_res.risk_level,
                patch_data=proposal.patch,
                diff=val_res.diff,
                is_auto_applied=False,
            )

            self._emit_event(on_event, {
                "event": "heal_proposed",
                "signature": detected.signature,
                "attempt": attempt_number,
                "status": "awaiting_approval",
                "diff": val_res.diff,
                "auto_applied": False,
                "reasoning": proposal.reasoning,
                "confidence": proposal.confidence,
                "risk_level": val_res.risk_level,
            })

            return False, val_res.patched_ir, val_res.patched_hcl, detected, heal_rec

    def approve_heal(
        self,
        attempt_id: Optional[int] = None,
        plan_id: Optional[str] = None,
        attempt_number: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> HealingAttemptRecord:
        """Human approves a proposed healing attempt."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            if attempt_id is not None:
                rec = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.id == attempt_id).first()
            elif plan_id and attempt_number:
                rec = db.query(HealingAttemptRecord).filter(
                    HealingAttemptRecord.plan_id == plan_id,
                    HealingAttemptRecord.attempt_number == attempt_number,
                ).first()
            else:
                raise ValueError("Must provide attempt_id or plan_id + attempt_number.")

            if not rec:
                raise ValueError("Healing attempt record not found.")

            rec.status = "approved"
            rec.updated_at = datetime.datetime.utcnow()

            # Apply patch to plan main.tf and IR
            plan_rec = db.query(PlanRecord).filter(PlanRecord.plan_id == rec.plan_id).first()
            if plan_rec and rec.patch_data:
                try:
                    patch_dict = json.loads(rec.patch_data)
                    curr_ir = UniversalIR(**json.loads(plan_rec.ir_json))
                    ir_dict = curr_ir.model_dump()
                    fix_validator._apply_ir_patch(ir_dict, patch_dict)
                    patched_ir = UniversalIR(**ir_dict)
                    plan_rec.ir_json = patched_ir.model_dump_json()

                    # Regenerate main.tf
                    plan_dir = Path(settings.TERRAFORM_WORKSPACE) / rec.plan_id
                    if plan_dir.exists():
                        from app.engines.terraform_generator import tf_generator
                        real_env = getattr(plan_rec, "environment", None) or (patched_ir.cloud.environment if patched_ir.cloud else None) or "local"
                        tf_generator.generate(patched_ir, environment=real_env, plan_id=rec.plan_id)
                        new_hcl = (plan_dir / "main.tf").read_text(encoding="utf-8")
                        plan_rec.terraform_code = new_hcl
                except Exception as e:
                    logger.warning("Notice applying approved patch", error=str(e))

            db.commit()

            audit_logger.log(
                event_type="HEAL_APPLIED",
                plan_id=rec.plan_id,
                risk_level=rec.risk_assessment,
                action_by="human_operator",
                details={
                    "signature": rec.error_signature,
                    "attempt": rec.attempt_number,
                    "decision": "approved",
                },
                db=db,
            )

            # Record success in learning loop
            kb_manager.record_success(
                signature=rec.error_signature,
                fix_type=rec.fix_type,
                db=db,
            )

            return rec
        finally:
            if close_db:
                db.close()

    def reject_heal(
        self,
        attempt_id: Optional[int] = None,
        plan_id: Optional[str] = None,
        attempt_number: Optional[int] = None,
        reason: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> HealingAttemptRecord:
        """Human rejects a proposed healing attempt."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            if attempt_id is not None:
                rec = db.query(HealingAttemptRecord).filter(HealingAttemptRecord.id == attempt_id).first()
            elif plan_id and attempt_number:
                rec = db.query(HealingAttemptRecord).filter(
                    HealingAttemptRecord.plan_id == plan_id,
                    HealingAttemptRecord.attempt_number == attempt_number,
                ).first()
            else:
                raise ValueError("Must provide attempt_id or plan_id + attempt_number.")

            if not rec:
                raise ValueError("Healing attempt record not found.")

            rec.status = "rejected"
            rec.updated_at = datetime.datetime.utcnow()
            db.commit()

            audit_logger.log(
                event_type="HEAL_REJECTED",
                plan_id=rec.plan_id,
                risk_level=rec.risk_assessment,
                action_by="human_operator",
                details={
                    "signature": rec.error_signature,
                    "attempt": rec.attempt_number,
                    "decision": "rejected",
                    "reason": reason or "Rejected by operator",
                },
                db=db,
            )

            # Record failure in circuit breaker
            kb_manager.record_failure(
                signature=rec.error_signature,
                plan_id=rec.plan_id,
                db=db,
            )

            return rec
        finally:
            if close_db:
                db.close()

    def _create_healing_record(
        self,
        db: Session,
        execution_id: Optional[int],
        plan_id: str,
        attempt_number: int,
        detected: DetectedError,
        status: str,
        remediation_class: str = "auto",
        fix_type: str = "ir_patch",
        root_cause: str = "",
        reasoning: str = "",
        confidence: float = 1.0,
        risk_assessment: str = "low",
        patch_data: Optional[Dict[str, Any]] = None,
        diff: Optional[Dict[str, Any]] = None,
        is_auto_applied: bool = False,
    ) -> HealingAttemptRecord:
        """Persist a HealingAttemptRecord in DB."""
        rec = HealingAttemptRecord(
            execution_id=execution_id,
            plan_id=plan_id,
            attempt_number=attempt_number,
            error_signature=detected.signature,
            error_class=detected.error_class,
            error_message=detected.message,
            remediation_class=remediation_class,
            fix_type=fix_type,
            root_cause=root_cause or detected.message,
            reasoning=reasoning or detected.diagnosis or "",
            confidence=confidence,
            risk_assessment=risk_assessment,
            patch_data=json.dumps(patch_data) if patch_data else None,
            diff=json.dumps(diff) if diff else None,
            status=status,
            is_auto_applied=is_auto_applied,
        )
        db.add(rec)

        # Update execution record if present
        if execution_id:
            exec_rec = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if exec_rec:
                exec_rec.healing_status = status
                exec_rec.healing_attempts_count = attempt_number

        db.commit()
        db.refresh(rec)
        return rec

    def _emit_event(self, callback: Optional[Callable[[Dict[str, Any]], None]], event: Dict[str, Any]) -> None:
        """Helper to invoke on_event callback safely."""
        if callback:
            try:
                callback(event)
            except Exception as e:
                logger.warning("Notice emitting heal event", error=str(e))


self_healing_engine = SelfHealingEngine()

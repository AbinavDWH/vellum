import uuid
import json
import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.llm.client import llm_client
from app.validation.syntax import SyntaxValidator
from app.validation.security import SecurityValidator
from app.validation.policy import PolicyEngine, RiskLevel
from app.approval.engine import approval_engine
from app.adapters.database.base import get_database_adapter
from app.engines.terraform_generator import tf_generator
from app.engines.execution_engine import execution_engine
from app.engines.verification_engine import verification_engine
from app.engines.rag_engine import rag_engine
from app.rag.service import get_rag_service
from app.audit.logger import audit_logger
from app.models import PlanRecord, ApprovalRecord, ExecutionRecord, MessageRecord
from app.database import SessionLocal
from app.schemas.api import ChatResponse, PlanResponse, ExecutionResult, VerificationResult
from app.schemas.ir import UniversalIR, ClarificationQuestion, ClarificationResponse
from app.environment.inventory import environment_inventory
from app.validation.environment_conflict import environment_conflict_validator
from app.requirements import requirements_manager

logger = structlog.get_logger(__name__)


class VellumOrchestrator:
    """Core autonomous orchestrator coordinating LLM, approval, generation, execution, and verification."""

    def __init__(self):
        pass

    def _is_planning_intent(self, prompt: str) -> bool:
        """Determine if user wants to directly generate a plan vs. converse with the AI architect."""
        clean = prompt.strip().lower()
        if clean.startswith(("[plan]", "[generate]", "[deploy]", "[build]", "plan:", "deploy:", "synthesize:")):
            return True

        # Planning triggers
        plan_phrases = [
            "plan it", "generate plan", "synthesize plan", "build it", "deploy it",
            "create plan", "make plan", "synthesize", "generate the plan", "let's build",
            "looks good, plan", "proceed with plan", "ready to plan", "generate terraform",
            "create terraform", "let's deploy", "start deployment", "execute plan",
            "plan this", "generate hcl", "build this", "build the infrastructure"
        ]
        if any(p in clean for p in plan_phrases):
            return True

        # Imperative creation commands (e.g. "Create an S3 bucket...", "Deploy a postgres database...")
        imperative_verbs = ["create", "deploy", "provision", "launch", "setup", "spin up", "generate", "build"]
        resource_nouns = ["bucket", "database", "vpc", "subnet", "instance", "cluster", "s3", "rds", "ec2", "table", "schema"]

        words = clean.split()
        first_words = words[:4] if len(words) >= 4 else words
        has_verb = any(v in first_words for v in imperative_verbs) or clean.startswith(tuple(imperative_verbs))
        has_noun = any(n in clean for n in resource_nouns)
        if has_verb and has_noun:
            return True

        return False

    def process_natural_language(
        self,
        prompt: str,
        cloud_provider: str = "aws",
        environment: str = "local",
        session_id: str = "default",
        db: Optional[Session] = None,
        force_plan: bool = False,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ChatResponse:
        """
        Main entry point for user requests:
        1. Load and maintain session requirements.md
        2. If conversational request: converse with AI architect, update requirements.md, and return conversation response
        3. If planning request: retrieve RAG context, generate Universal IR from requirements.md + prompt, validate, and produce plan
        """
        logger.info("Processing NL infrastructure request", prompt=prompt, session_id=session_id)

        # Check if environment is explicitly mentioned in prompt or active connection
        prompt_lower = prompt.lower()
        if "prod" in prompt_lower or "production" in prompt_lower:
            if environment == "local" and not ("localstack" in prompt_lower or "locally" in prompt_lower or "local" in prompt_lower):
                environment = "prod"
        elif environment == "local" and not ("localstack" in prompt_lower or "locally" in prompt_lower or "local" in prompt_lower):
            try:
                from app.credentials.manager import credential_manager
                active_prod = credential_manager.get_active_connection(environment="prod", db=db)
                if active_prod and not credential_manager.get_active_connection(environment="local", db=db):
                    environment = "prod"
            except Exception:
                pass

        # Load current session requirements.md
        current_req_md = requirements_manager.get_requirements(
            session_id=session_id,
            cloud_provider=cloud_provider,
            environment=environment,
            db=db,
        )

        if current_req_md and environment == "local":
            import re
            env_match = re.search(r'\*\*Environment\*\*:\s*([a-zA-Z0-9_-]+)', current_req_md, re.IGNORECASE)
            if env_match and env_match.group(1).lower() in ["prod", "production", "staging"]:
                if not ("localstack" in prompt_lower or "locally" in prompt_lower or "local" in prompt_lower):
                    environment = "prod" if env_match.group(1).lower() in ["prod", "production"] else env_match.group(1).lower()

        if current_req_md and environment in ["prod", "staging"]:
            import re
            synced_md = re.sub(r'(\*\*Environment\*\*:\s*)[a-zA-Z0-9_-]+', rf'\g<1>{environment}', current_req_md, flags=re.IGNORECASE)
            synced_md = re.sub(r'(\*\*Cloud Provider\*\*:\s*)[a-zA-Z0-9_-]+', rf'\g<1>{cloud_provider.upper()}', synced_md, flags=re.IGNORECASE)
            if synced_md != current_req_md:
                current_req_md = requirements_manager.save_requirements(session_id=session_id, content=synced_md, db=db)

        # RAG grounded documentation retrieval + conversation memory
        rag_service = get_rag_service()
        search_query = prompt[:300].strip() if len(prompt) > 300 else prompt
        grounded_ctx = rag_service.assemble_grounded_context(search_query)
        memory_ctx = rag_engine.retrieve_context(search_query, session_id=session_id, db=db)

        rag_sections = []
        if grounded_ctx.has_sufficient_context:
            rag_sections.append(
                "Authoritative Provider Documentation & CIS Benchmarks (RAG Grounded):\n"
                + grounded_ctx.formatted_context
            )
            logger.info("RAG grounded documentation retrieved", doc_count=len(grounded_ctx.citations))
        if memory_ctx:
            rag_sections.append(memory_ctx)

        combined_rag_context = "\n\n---\n\n".join(rag_sections) if rag_sections else None

        citations_summary = [
            {
                "tag": c.citation_tag,
                "title": c.title,
                "domain": c.domain,
                "resource_type": c.resource_type,
                "score": round(c.final_score, 4),
            }
            for c in grounded_ctx.citations
        ] if (grounded_ctx and grounded_ctx.has_sufficient_context) else []

        # Check if user wants to generate a concrete plan or hold a conversation
        is_planning = force_plan or self._is_planning_intent(prompt)

        if not is_planning:
            # Conversational Architect Turn: Chat naturally and update requirements.md
            history = []
            if db is not None:
                try:
                    records = (
                        db.query(MessageRecord)
                        .filter(MessageRecord.session_id == session_id)
                        .order_by(MessageRecord.created_at.asc())
                        .all()
                    )
                    history = [{"role": m.role, "content": m.content} for m in records]
                except Exception:
                    pass

            ai_message = llm_client.chat_architect(
                prompt=prompt,
                history=history,
                current_requirements_md=current_req_md,
                cloud_provider=cloud_provider,
                environment=environment,
                rag_context=combined_rag_context,
                model=model,
                provider=provider,
            )

            # Update the living requirements.md
            updated_req_md = llm_client.synthesize_requirements(
                current_requirements_md=current_req_md,
                prompt=prompt,
                ai_response=ai_message,
                cloud_provider=cloud_provider,
                environment=environment,
                model=model,
                provider=provider,
            )
            requirements_manager.save_requirements(session_id=session_id, content=updated_req_md, db=db)

            # Generate interactive architecture questions with choice option badges
            clarification = llm_client.generate_architecture_questions(
                prompt=prompt,
                current_requirements_md=updated_req_md,
                cloud_provider=cloud_provider,
                environment=environment,
                history=history,
                model=model,
                provider=provider,
            )

            return ChatResponse(
                status="conversation",
                message=ai_message,
                clarification=clarification if (clarification and clarification.questions) else None,
                rag_citations=citations_summary if citations_summary else None,
                requirements_md=updated_req_md,
            )

        # Planning Turn: Synthesize Universal IR using accumulated requirements.md and user prompt
        # Update requirements.md with any new parameters in the planning prompt
        updated_req_md = llm_client.synthesize_requirements(
            current_requirements_md=current_req_md,
            prompt=prompt,
            ai_response="Synthesizing concrete infrastructure and database plan.",
            cloud_provider=cloud_provider,
            environment=environment,
            model=model,
            provider=provider,
        )
        requirements_manager.save_requirements(session_id=session_id, content=updated_req_md, db=db)
        current_req_md = updated_req_md

        ir = llm_client.generate_ir(
            prompt,
            rag_context=combined_rag_context,
            requirements_md=current_req_md,
            model=model,
            provider=provider,
        )
        if ir.cloud:
            ir.cloud.provider = cloud_provider
            ir.cloud.environment = environment

        # Scope Fidelity Check (F4: SCOPE_FIDELITY)
        from app.validation.scope_fidelity import ScopeFidelityValidator
        is_scope_valid, scope_errors, annotated_ir = ScopeFidelityValidator.validate(prompt, ir)
        if not is_scope_valid:
            logger.warning("SCOPE_FIDELITY violation in generated plan, attempting planner re-generation", errors=scope_errors)
            corrective_prompt = (
                f"SCOPE_FIDELITY VIOLATION:\n"
                f"You generated unrequested resources that were not asked for: {'; '.join(scope_errors)}.\n"
                f"The user ONLY requested: '{prompt}'.\n"
                f"Rule: Create ONLY explicitly requested resources or strict technical dependencies. "
                f"Remove all unrequested databases, tables, S3 buckets, or VPCs. "
                f"Output strictly corrected Universal IR JSON."
            )
            try:
                re_ir = llm_client.generate_ir(
                    corrective_prompt,
                    requirements_md="",
                    model=model,
                    provider=provider,
                )
                re_valid, re_errors, re_annotated = ScopeFidelityValidator.validate(prompt, re_ir)
                if re_valid:
                    ir = re_annotated
                    is_scope_valid = True
            except Exception as re_ex:
                logger.warning("Re-prompting planner on SCOPE_FIDELITY failed", error=str(re_ex))

        if not is_scope_valid:
            # Deterministic pruning fallback to guarantee scope fidelity
            intents = ScopeFidelityValidator.analyze_user_intent(prompt)
            if not intents["wants_database"]:
                ir.database = None
                if ir.cloud and ir.cloud.resources:
                    ir.cloud.resources = [r for r in ir.cloud.resources if r.type not in ["managed_database", "rds", "aws_db_instance", "db_subnet_group"]]
            if not intents["wants_network"] and (intents["wants_static_site"] or intents["wants_storage"]):
                if ir.cloud and ir.cloud.resources:
                    ir.cloud.resources = [r for r in ir.cloud.resources if r.type not in ["virtual_network", "vpc", "subnet", "public_subnet", "private_subnet", "internet_gateway", "route_table"]]
            if not (intents["wants_static_site"] or intents["wants_storage"]) and intents["wants_network"]:
                if ir.cloud and ir.cloud.resources:
                    ir.cloud.resources = [r for r in ir.cloud.resources if r.type not in ["object_storage", "s3_bucket", "storage_bucket", "static_site", "website_hosting"]]

            # Re-validate
            _, _, annotated_ir = ScopeFidelityValidator.validate(prompt, ir)
            ir = annotated_ir
        else:
            ir = annotated_ir

        # Pre-Flight Environment Introspection & Conflict Prevention (M-15)
        user_choices = environment_conflict_validator.parse_user_choices_from_prompt(prompt)
        target_region = ir.cloud.region if ir.cloud else "us-east-1"
        snapshot = environment_inventory.get_snapshot(
            provider=cloud_provider,
            region=target_region,
            environment=environment,
            force_rescan=False,
            db=db,
        )
        conflicts, patched_ir, has_unresolved_ask_user, is_blocked = environment_conflict_validator.validate_and_resolve(
            ir=ir,
            snapshot=snapshot,
            user_choices=user_choices,
        )

        if is_blocked:
            block_reasons = [c.proposed_action for c in conflicts if c.strategy == "fail-fast"]
            reason_msg = "; ".join(block_reasons) or "Plan blocked due to pre-flight governance policy."
            return ChatResponse(
                status="error",
                message=f"Pre-flight conflict prevention halted execution: {reason_msg}",
            )

        if has_unresolved_ask_user:
            ask_questions = [
                ClarificationQuestion(
                    question=f"Resource '{c.original_name}' already exists in target environment.",
                    context=f"Pre-flight scan detected an existing {c.resource_type} ('{c.original_name}'). Choose how Vellum should resolve the collision:",
                    default_suggestion=c.options[0] if c.options else "Reuse & manage",
                    options=c.options,
                    conflict_type=c.conflict_type,
                    resource_name=c.original_name,
                )
                for c in conflicts if c.strategy == "ask-user"
            ]
            return ChatResponse(
                status="clarification_needed",
                message="Pre-flight environment introspection detected conflicts that require your input before approval:",
                clarification=ClarificationResponse(is_ready=False, questions=ask_questions),
            )

        ir = patched_ir

        # 3. Service Scope Check (M-17: SERVICE_IN_SCOPE)
        from app.credentials.manager import credential_manager
        active_conn = credential_manager.get_active_connection(environment=environment, db=db)
        if active_conn:
            is_in_scope, scope_errors = credential_manager.validate_service_scope(ir, active_conn)
            if not is_in_scope:
                return ChatResponse(
                    status="error",
                    message="Validation failed (SERVICE_IN_SCOPE): " + "; ".join(scope_errors),
                )

        # 4. Syntax validation
        is_valid, syntax_errors = SyntaxValidator.validate(ir)
        if not is_valid:
            logger.warning("Syntax validation had warnings", errors=syntax_errors)

        # 5. Security Audit
        security_findings = SecurityValidator.audit(ir)

        # 6. Risk & Policy Evaluation
        risk = approval_engine.classify_risk(ir)
        requires_conf, conf_phrase = approval_engine.get_confirmation_requirements(ir)
        if active_conn and active_conn.environment == "prod":
            risk = RiskLevel.CRITICAL
            requires_conf = True
            conf_phrase = active_conn.name
        ir.risk_level = risk.value

        # Heuristic cost calculation
        cost = self._calculate_cost(ir)
        ir.estimated_cost_monthly = cost

        # Ensure implementation_plan is built (F7: infra -> config -> content -> verify -> handoff)
        if not ir.implementation_plan:
            ir.implementation_plan = self._build_implementation_plan(ir)

        # 6. Generate Code
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan_dir = tf_generator.generate(ir, environment=environment, plan_id=plan_id)
        
        main_tf_path = f"{plan_dir}/main.tf"
        generated_tf = ""
        try:
            with open(main_tf_path, "r", encoding="utf-8") as f:
                generated_tf = f.read()
        except Exception:
            pass

        generated_sql = ""
        if ir.database:
            adapter = get_database_adapter(ir.database.provider)
            generated_sql = adapter.generate_ddl(ir.database)


        # 7. Summary preview
        summary = approval_engine.format_plan_preview(ir)

        # 8. Persist Plan
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            plan_record = PlanRecord(
                plan_id=plan_id,
                connection_id=active_conn.id if active_conn else None,
                prompt=prompt,
                intent=ir.intent,
                risk_level=risk.value,
                status="awaiting_approval",
                confirmation_phrase=conf_phrase,
                requires_confirmation_text=requires_conf,
                ir_json=ir.model_dump_json(),
                terraform_code=generated_tf,
                sql_code=generated_sql,
                estimated_cost_monthly=cost,
                security_checks_json=json.dumps(security_findings),
            )
            db.add(plan_record)
            db.commit()

            # Audit log
            audit_logger.log(
                event_type="PLAN_GENERATED",
                plan_id=plan_id,
                risk_level=risk.value,
                details={
                    "intent": ir.intent,
                    "risk_level": risk.value,
                    "cost": cost,
                    "security_findings_count": len(security_findings),
                },
                db=db,
            )

            # Audit log: CONFLICT_RESOLVED for any resolved conflicts (M-15)
            for c in conflicts:
                if c.strategy in ["reuse", "rename", "auto-recompute", "auto-fix", "auto-fallback"]:
                    audit_logger.log(
                        event_type="CONFLICT_RESOLVED",
                        plan_id=plan_id,
                        risk_level="low",
                        action_by="preflight_conflict_engine",
                        details={
                            "strategy": c.strategy,
                            "resource": c.original_name,
                            "before": c.original_name,
                            "after": c.new_value,
                            "snapshot_hash": snapshot.snapshot_hash,
                            "conflict_type": c.conflict_type,
                            "status_chip": c.status_chip,
                            "details": c.details,
                        },
                        db=db,
                    )

        except Exception as e:
            logger.error("Failed to save plan to DB", error=str(e))
            db.rollback()
        finally:
            if close_db:
                db.close()

        plan_res = PlanResponse(
            plan_id=plan_id,
            status="awaiting_approval",
            intent=ir.intent,
            risk_level=risk.value,
            requires_confirmation_text=requires_conf,
            confirmation_phrase=conf_phrase,
            summary_preview=summary,
            ir=ir,
            generated_terraform=generated_tf,
            generated_sql=generated_sql,
            estimated_cost_monthly=cost,
            security_checks=security_findings,
            implementation_plan=ir.implementation_plan or [],
            created_at=datetime.datetime.utcnow().isoformat(),
        )

        citations_summary = [
            {
                "tag": c.citation_tag,
                "title": c.title,
                "domain": c.domain,
                "resource_type": c.resource_type,
                "score": round(c.final_score, 4),
            }
            for c in grounded_ctx.citations
        ] if (grounded_ctx and grounded_ctx.has_sufficient_context) else []

        grounded_suffix = f" (grounded with {len(citations_summary)} official specifications)" if citations_summary else ""
        return ChatResponse(
            status="plan_ready",
            message=f"I have designed the infrastructure plan based on your requirement{grounded_suffix}. Risk level: {risk.value.upper()}. Human approval is required to execute.",
            plan=plan_res,
            rag_citations=citations_summary,
            requirements_md=current_req_md,
        )

    def plan_from_requirements(
        self,
        session_id: str = "default",
        cloud_provider: str = "aws",
        environment: str = "local",
        db: Optional[Session] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ChatResponse:
        """Synthesize infrastructure and database plan directly from the accumulated session requirements.md."""
        req_md = requirements_manager.get_requirements(
            session_id=session_id,
            cloud_provider=cloud_provider,
            environment=environment,
            db=db,
        )
        if req_md and environment == "local":
            import re
            env_match = re.search(r'\*\*Environment\*\*:\s*([a-zA-Z0-9_-]+)', req_md, re.IGNORECASE)
            if env_match and env_match.group(1).lower() in ["prod", "production", "staging"]:
                environment = "prod" if env_match.group(1).lower() in ["prod", "production"] else env_match.group(1).lower()

        if req_md and environment in ["prod", "staging"]:
            import re
            synced_md = re.sub(r'(\*\*Environment\*\*:\s*)[a-zA-Z0-9_-]+', rf'\g<1>{environment}', req_md, flags=re.IGNORECASE)
            synced_md = re.sub(r'(\*\*Cloud Provider\*\*:\s*)[a-zA-Z0-9_-]+', rf'\g<1>{cloud_provider.upper()}', synced_md, flags=re.IGNORECASE)
            if synced_md != req_md:
                req_md = requirements_manager.save_requirements(session_id=session_id, content=synced_md, db=db)

        directive = f"Synthesize complete infrastructure plan based on the documented requirements specification:\n\n{req_md}"
        return self.process_natural_language(
            prompt=directive,
            cloud_provider=cloud_provider,
            environment=environment,
            session_id=session_id,
            db=db,
            force_plan=True,
            model=model,
            provider=provider,
        )

    def _build_implementation_plan(self, ir: UniversalIR) -> List[Dict[str, Any]]:
        """Construct ordered, human-readable implementation steps (F7: infra -> config -> content -> verify -> handoff)."""
        is_static_site = (ir.intent == "deploy_static_site") or any(
            r.properties.get("website") is True for r in (ir.cloud.resources if ir.cloud else [])
        )
        has_database = bool(ir.database and ir.database.tables) or any(
            r.type in ["managed_database", "rds"] for r in (ir.cloud.resources if ir.cloud else [])
        )
        has_network = any(
            r.type in ["virtual_network", "vpc"] for r in (ir.cloud.resources if ir.cloud else [])
        )

        # Step 1: Infra
        infra_desc = "Provision baseline cloud infrastructure via Terraform."
        if is_static_site:
            infra_desc = "Provision Amazon S3 bucket with website configuration enabled."
        elif has_network and has_database:
            infra_desc = "Provision VPC networking, subnets, and RDS database instance."
        elif has_network:
            infra_desc = "Provision VPC, public/private subnets, and Internet Gateway."
        elif has_database:
            infra_desc = "Provision managed database instance or schema container."

        # Step 2: Config
        config_desc = "Configure security groups and networking access rules."
        if is_static_site:
            config_desc = "Configure S3 bucket policy (public-read) and public access block controls."
        elif has_network:
            config_desc = "Attach Internet Gateway, configure public route table (0.0.0.0/0 -> IGW), and associate subnets."
        elif has_database:
            config_desc = "Configure DB subnet groups, parameter groups, and ingress security group rules."

        # Step 3: Content / Schema
        content_desc = "Deploy application components and schema migrations."
        if is_static_site:
            src_type = ir.site_source.get("type", "source") if ir.site_source else "source"
            content_desc = f"Fetch static site content from {src_type} and sync to S3 with extension MIME types."
        elif has_database:
            table_count = len(ir.database.tables) if ir.database and ir.database.tables else 1
            content_desc = f"Execute database DDL schema to provision {table_count} tables, primary keys, and indexes."
        else:
            content_desc = "Verify resource connectivity and tag metadata compliance."

        # Step 4: Verification
        verify_desc = "Execute 100% per-resource functional verification (F6: HTTP 200, head bucket, route check, db available)."

        # Step 5: Handoff
        handoff_desc = "Emit public endpoint URL, resource inventory, wire traces, and estimated monthly cost."

        return [
            {
                "step_number": 1,
                "name": "Infrastructure Provisioning",
                "phase": "infra",
                "description": infra_desc,
                "status": "pending",
            },
            {
                "step_number": 2,
                "name": "Configuration & Security",
                "phase": "config",
                "description": config_desc,
                "status": "pending",
            },
            {
                "step_number": 3,
                "name": "Content & Schema Deployment",
                "phase": "content",
                "description": content_desc,
                "status": "pending",
            },
            {
                "step_number": 4,
                "name": "Functional Verification",
                "phase": "verify",
                "description": verify_desc,
                "status": "pending",
            },
            {
                "step_number": 5,
                "name": "Operational Handoff",
                "phase": "handoff",
                "description": handoff_desc,
                "status": "pending",
            },
        ]

    def _calculate_cost(self, ir: UniversalIR) -> float:
        """Estimate monthly cost for cloud resources."""
        cost = 0.0
        if not ir.cloud:
            return cost
        for res in ir.cloud.resources:
            r_type = res.type
            if r_type == "virtual_network":
                cost += 0.0  # VPC is free
            elif r_type == "subnet":
                cost += 0.0
            elif r_type == "object_storage":
                cost += 5.0  # baseline S3
            elif r_type == "managed_database":
                cost += 15.0  # db.t3.micro
            elif r_type == "compute_instance":
                cost += 10.0  # t3.micro
        return round(cost, 2)

    def execute_approved_plan(
        self,
        plan_id: str,
        on_log=None,
        on_event=None,
        db: Optional[Session] = None,
    ) -> ExecutionResult:
        """Executes a plan that was approved with self-healing support (M-14)."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        plan = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
        if not plan:
            if close_db:
                db.close()
            return ExecutionResult(plan_id=plan_id, success=False, status="failed", error_message="Plan not found")

        # Connection existence & deletion guard (M-17)
        if plan.connection_id:
            from app.models import ConnectionRecord
            conn = db.query(ConnectionRecord).filter(ConnectionRecord.id == plan.connection_id).first()
            if not conn or conn.is_deleted:
                plan.status = "failed"
                db.commit()
                if close_db:
                    db.close()
                return ExecutionResult(
                    plan_id=plan_id,
                    success=False,
                    status="failed",
                    error_message=f"Connection '{plan.connection_id}' has been deleted. Re-associate with an active connection before planning or executing.",
                )

        plan.status = "executing"
        db.commit()

        audit_logger.log(
            event_type="EXECUTION_STARTED",
            plan_id=plan_id,
            risk_level=plan.risk_level,
            details={"plan_id": plan_id},
            db=db,
        )

        ir_obj = None
        if plan.ir_json:
            try:
                ir_obj = UniversalIR(**json.loads(plan.ir_json))
            except Exception:
                pass

        existing_runs = db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).count()
        run_number = existing_runs + 1

        exec_record = ExecutionRecord(
            plan_id=plan_id,
            run_number=run_number,
            status="executing",
            success=False,
            healing_status="none",
            healing_attempts_count=0,
            started_at=datetime.datetime.utcnow(),
        )
        db.add(exec_record)
        db.commit()
        db.refresh(exec_record)

        plan_dir = f"{settings.TERRAFORM_WORKSPACE}/{plan_id}"
        exec_res = execution_engine.execute_plan(
            plan_dir=plan_dir,
            plan_id=plan_id,
            on_log=on_log,
            on_event=on_event,
            execution_id=exec_record.id,
            current_ir=ir_obj,
            db=db,
        )

        # Database schema execution if database tables defined
        if exec_res.success and plan.ir_json and plan.sql_code:
            try:
                ir_dict = json.loads(plan.ir_json)
                ir_database_obj = UniversalIR(**ir_dict)
                if ir_database_obj.database and ir_database_obj.database.tables:
                    db_provider = ir_database_obj.database.provider or "postgresql"
                    if on_log:
                        on_log(f"📦 Provisioning database tables on {db_provider}...")
                    db_ok = execution_engine.execute_database(ir_database_obj.database)
                    if on_log:
                        if db_ok:
                            on_log(f"✅ Successfully provisioned {len(ir_database_obj.database.tables)} database tables in {db_provider}.")
                        else:
                            on_log(f"⚠️ Notice: Database provisioning returned status warning.")
            except Exception as dbe:
                logger.warning("Database DDL execution notice", error=str(dbe))
                if on_log:
                    on_log(f"ℹ️ Database execution note: {str(dbe)}")

        # F6: Per-resource functional verification before declaring COMPLETED
        resource_checklist = []
        is_fully_verified = False

        if exec_res.success and ir_obj:
            if on_log:
                on_log("🔍 [F6] Executing 100% per-resource functional verification checks...")

            # Resolve connection info for target environment
            resolved_key = None
            resolved_secret = None
            target_env = "local"
            target_region = ir_obj.cloud.region if ir_obj.cloud else "us-east-1"
            if plan.connection_id:
                from app.models import ConnectionRecord
                from app.credentials.manager import credential_manager
                conn = db.query(ConnectionRecord).filter(ConnectionRecord.id == plan.connection_id).first()
                if conn and not conn.is_deleted:
                    target_env = conn.environment or target_env
                    target_region = conn.region or target_region
                    if conn.encrypted_access_key and conn.encrypted_secret_key:
                        resolved_key = credential_manager.decrypt(conn.encrypted_access_key)
                        resolved_secret = credential_manager.decrypt(conn.encrypted_secret_key)

            v_report = verification_engine.verify(
                plan_id=plan_id,
                expected_ir=ir_obj,
                environment=target_env,
                aws_access_key=resolved_key,
                aws_secret_key=resolved_secret,
                region=target_region,
                db=db,
            )

            resource_checklist = v_report.get("details", {}).get("resource_checklist", [])
            exec_res.resource_checklist = resource_checklist

            missing_resources = v_report.get("missing_resources", [])
            failed_functional = [
                item for item in resource_checklist if not item.get("functional_green")
            ]

            if not missing_resources and not failed_functional and v_report.get("status") == "success":
                is_fully_verified = True
                if on_log:
                    on_log(f"✅ [F6] 100% functional verification passed ({len(resource_checklist)}/{len(resource_checklist)} resources green).")
            else:
                fail_reasons = []
                if missing_resources:
                    fail_reasons.append(f"Missing resources: {', '.join(missing_resources)}")
                for ff in failed_functional:
                    fail_reasons.append(f"{ff.get('name')}: {ff.get('error') or ff.get('details')}")

                fail_msg = f"Functional verification failed: {'; '.join(fail_reasons)}"
                if on_log:
                    on_log(f"❌ [F6] {fail_msg}")
                logger.warning("F6 functional verification failed", plan_id=plan_id, reasons=fail_reasons)

                exec_res.success = False
                exec_res.status = "partial_failed"
                exec_res.error_message = fail_msg

                # M-20 Policy: Auto-rollback on failure if configured
                created_this_run = exec_res.created_resources or []
                should_auto_rollback = False
                if plan and plan.execution_policy_json:
                    try:
                        pol = json.loads(plan.execution_policy_json)
                        if pol.get("on_failure") == "auto_destroy":
                            should_auto_rollback = True
                    except Exception:
                        pass

                if should_auto_rollback and created_this_run:
                    if on_log:
                        on_log(f"🧨 [AUTO-ROLLBACK] Policy triggered. Rolling back resources: {created_this_run}...")
                    execution_engine.rollback(
                        plan_dir=plan_dir,
                        plan_id=plan_id,
                        db=db,
                        on_log=on_log,
                        target_resources=created_this_run,
                    )
                    exec_res.status = "rolled_back"
                    exec_res.error_message = f"Execution failed verification ({fail_msg}). Rolled back newly created resources."

        # Update DB record with honest status (F6)
        if exec_res.success and (is_fully_verified or not ir_obj):
            plan.status = "completed"
        elif exec_res.status in ["partial_failed", "rolled_back", "halted"]:
            plan.status = exec_res.status
        else:
            plan.status = "failed"

        exec_res.run_number = run_number

        exec_record.status = exec_res.status
        exec_record.success = exec_res.success
        exec_record.resources_created = exec_res.resources_created
        exec_record.resources_updated = exec_res.resources_updated
        exec_record.resources_deleted = exec_res.resources_deleted
        exec_record.terraform_output = exec_res.terraform_output
        exec_record.sql_output = exec_res.sql_output
        exec_record.error_message = exec_res.error_message
        exec_record.duration_seconds = exec_res.execution_time_seconds
        exec_record.wire_traces_count = exec_res.wire_traces_count
        if resource_checklist:
            exec_record.resource_checklist_json = json.dumps(resource_checklist)
        if exec_res.created_resources:
            exec_record.created_resources_json = json.dumps(exec_res.created_resources)
        exec_record.completed_at = datetime.datetime.utcnow()

        # Update linked session status if applicable
        from app.models import SessionRecord
        session = db.query(SessionRecord).filter(SessionRecord.last_plan_id == plan_id).first()
        if session:
            session.status = "has-completed-plan" if (exec_res.success and is_fully_verified) else "failed"

        db.commit()

        audit_logger.log(
            event_type="EXECUTION_COMPLETED" if (exec_res.success and is_fully_verified) else ("EXECUTION_PARTIAL_FAILURE" if exec_res.status == "partial_failed" else "EXECUTION_FAILED"),
            plan_id=plan_id,
            risk_level=plan.risk_level,
            details={
                "success": exec_res.success,
                "status": exec_res.status,
                "resources_created": exec_res.resources_created,
                "duration": exec_res.execution_time_seconds,
                "checklist_count": len(resource_checklist),
            },
            db=db,
        )

        if close_db:
            db.close()

        return exec_res


orchestrator = VellumOrchestrator()

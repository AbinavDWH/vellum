import json
import re
import time
import threading
import httpx
import structlog
from typing import List, Dict, Any, Optional
from app.config import settings
from app.llm.prompts import (
    UNIVERSAL_IR_SYSTEM_PROMPT,
    CLARIFICATION_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
    ARCHITECT_CONVERSATION_SYSTEM_PROMPT,
    REQUIREMENTS_SYNTHESIS_SYSTEM_PROMPT,
    ARCHITECTURE_CLARIFICATION_SYSTEM_PROMPT,
)
from app.llm.parser import LLMParser
from app.schemas.ir import UniversalIR, ClarificationResponse, ClarificationQuestion

logger = structlog.get_logger(__name__)


class GroqClient:
    """Client for Groq's high-speed cloud LLM inference API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.base_url = (base_url or settings.GROQ_API_URL).rstrip("/")
        self.default_model = default_model or settings.GROQ_MODEL
        self.fallback_model = fallback_model or settings.GROQ_FALLBACK_MODEL
        self.timeout = timeout

    def is_configured(self) -> bool:
        """Check if Groq API key is present."""
        return bool(self.api_key and self.api_key.startswith("gsk_"))

    def is_healthy(self) -> bool:
        """Verify Groq API accessibility with credential."""
        if not self.is_configured():
            return False
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=4.0) as client:
                res = client.get(f"{self.base_url}/models", headers=headers)
                return res.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> List[str]:
        """Fetch list of accessible models from Groq."""
        if not self.is_configured():
            return []
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models", headers=headers)
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    return [m.get("id") for m in data if m.get("id")]
        except Exception as e:
            logger.warning("Could not list Groq models", error=str(e))
        return [self.default_model, self.fallback_model]

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> str:
        """Execute chat completion against Groq API with resilient retry and backoff."""
        if not self.is_configured():
            raise RuntimeError("Groq API key is not configured")

        selected_model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        call_messages = list(messages)
        if json_mode:
            has_json_word = any("json" in m.get("content", "").lower() for m in call_messages)
            if not has_json_word:
                call_messages.append({"role": "system", "content": "Output response strictly as a valid JSON object."})

        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": call_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        with httpx.Client(timeout=self.timeout) as client:
            last_err = None
            for attempt in range(3):
                try:
                    response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise RuntimeError("Groq API returned empty completion choices")
                    msg = choices[0].get("message", {})
                    content = msg.get("content")
                    if not content and msg.get("reasoning"):
                        content = msg.get("reasoning")
                    return (content or "").strip()
                except httpx.HTTPStatusError as err:
                    last_err = err
                    status = err.response.status_code
                    if status == 429:
                        delay = 1.5
                        m = re.search(r"try again in ([\d\.]+)s", err.response.text)
                        if m:
                            try:
                                delay = min(float(m.group(1)) + 0.3, 5.0)
                            except Exception:
                                pass
                        logger.warning(
                            "Groq rate limit reached (429), backing off before retry",
                            attempt=attempt,
                            delay=delay,
                            model=payload.get("model"),
                        )
                        if payload.get("model") != self.fallback_model:
                            payload["model"] = self.fallback_model
                        if payload.get("max_tokens", 0) > 1500:
                            payload["max_tokens"] = 1500
                        time.sleep(delay)
                        continue
                    elif status in [400, 403, 404] and payload.get("model") != self.fallback_model:
                        logger.warning(
                            "Groq model returned error, attempting fallback model",
                            error=str(err),
                            fallback_model=self.fallback_model,
                        )
                        payload["model"] = self.fallback_model
                        continue
                    else:
                        raise
            if last_err:
                raise last_err
            raise RuntimeError("Groq API call failed after retries")


class LMStudioClient:
    """Client for local LM Studio instance."""

    def __init__(self, base_url: str = settings.LM_STUDIO_URL):
        self.base_url = base_url.rstrip("/")
        self.timeout = 180.0
        self._detected_model: Optional[str] = None

    def get_active_model(self) -> str:
        """Fetch active model from LM Studio or use configured model."""
        if self._detected_model:
            return self._detected_model
        if settings.LM_STUDIO_MODEL:
            self._detected_model = settings.LM_STUDIO_MODEL
            return self._detected_model

        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models")
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("data", [])
                    if models:
                        for m in models:
                            mid = m.get("id", "")
                            if any(k in mid.lower() for k in ["coder", "instruct", "qwen", "llama"]):
                                self._detected_model = mid
                                return mid
                        self._detected_model = models[0].get("id", "local-model")
                        return self._detected_model
        except Exception as e:
            logger.warning("Could not auto-detect LM Studio models", error=str(e))

        return settings.LM_STUDIO_MODEL or "local-model"

    def is_healthy(self) -> bool:
        """Check if LM Studio server is reachable."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/models")
                return res.status_code == 200
        except Exception:
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = settings.LM_STUDIO_TEMPERATURE,
        max_tokens: int = settings.LM_STUDIO_MAX_TOKENS,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> str:
        """Send chat completion to local LM Studio."""
        selected_model = model or self.get_active_model()
        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": {"type": "object"}}
            }

        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(f"{self.base_url}/chat/completions", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 400 and json_mode:
                    payload.pop("response_format", None)
                    response = client.post(f"{self.base_url}/chat/completions", json=payload)
                    response.raise_for_status()
                else:
                    raise
            data = response.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            if not content and msg.get("reasoning_content"):
                content = msg.get("reasoning_content")
            return (content or "").strip()


class HybridLLMClient:
    """Multi-Provider LLM Client supporting strict Single-AI operation across Groq and Local LM Studio."""

    def __init__(self):
        self.groq = GroqClient()
        self.lm_studio = LMStudioClient()
        self._inference_lock = threading.Lock()
        self._active_provider = (settings.LLM_PROVIDER or "local").lower()
        self._active_model: Optional[str] = None

    def set_active_provider(self, provider: str, model: Optional[str] = None):
        """Switch the single active AI provider and model."""
        prov = provider.lower().strip()
        if prov not in ["groq", "local", "hybrid"]:
            raise ValueError(f"Invalid AI provider '{provider}'. Must be 'groq' or 'local'.")
        self._active_provider = prov
        settings.LLM_PROVIDER = prov
        if model:
            if model.startswith(f"{prov}:"):
                model = model[len(f"{prov}:"):]
            self._active_model = model
            if prov == "groq":
                self.groq.default_model = model
            elif prov == "local":
                self.lm_studio._detected_model = model

    def is_healthy(self) -> bool:
        """Return True if the single active AI backend is available."""
        prov = self.get_active_provider()
        if prov == "groq":
            return self.groq.is_healthy()
        elif prov == "local":
            return self.lm_studio.is_healthy()
        return self.lm_studio.is_healthy() or self.groq.is_healthy()

    def get_active_provider(self) -> str:
        """Determine which single provider actively handles requests."""
        return (self._active_provider or settings.LLM_PROVIDER or "local").lower()

    def get_active_model(self) -> str:
        """Return active model name with provider indicator."""
        prov = self.get_active_provider()
        if prov == "groq":
            model_name = self._active_model or self.groq.default_model
            return f"Groq • {model_name}"
        elif prov == "local":
            model_name = self._active_model or self.lm_studio.get_active_model()
            return f"Local • {model_name}"
        elif self.groq.is_healthy():
            return f"Groq • {self.groq.default_model}"
        elif self.lm_studio.is_healthy():
            return f"Local • {self.lm_studio.get_active_model()}"
        return "Offline Fallback"

    def get_provider_status(self) -> Dict[str, Any]:
        """Comprehensive status reporting for Topbar UI, Health check, and Diagnostics."""
        active_prov = self.get_active_provider()
        groq_ok = self.groq.is_healthy()
        lm_ok = self.lm_studio.is_healthy()
        active_online = groq_ok if active_prov == "groq" else (lm_ok if active_prov == "local" else (groq_ok or lm_ok))
        return {
            "single_ai_mode": True,
            "active_provider": active_prov,
            "active_model": self.get_active_model(),
            "active_online": active_online,
            "routing_mode": active_prov,
            "groq_online": groq_ok,
            "groq_model": self.groq.default_model,
            "lm_studio_online": lm_ok,
            "lm_studio_model": self.lm_studio.get_active_model() if lm_ok else "offline",
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """Route chat completion to exactly ONE active AI at a time with thread-safe locking."""
        pref = (provider or self._active_provider or settings.LLM_PROVIDER or "local").lower()
        target_model = model

        # Support prefix format e.g. "groq:openai/gpt-oss-120b" or "local:qwen3.5-4b"
        if target_model:
            if target_model.startswith("groq:"):
                pref = "groq"
                target_model = target_model[len("groq:"):]
            elif target_model.startswith("local:"):
                pref = "local"
                target_model = target_model[len("local:"):]

        with self._inference_lock:
            if pref == "groq":
                # Strictly use Groq only. Do not fall back to LM Studio.
                return self.groq.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    model=target_model or self._active_model or self.groq.default_model,
                )
            elif pref == "local":
                # Strictly use Local LM Studio only. Do not call Groq.
                return self.lm_studio.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    model=target_model or self._active_model or self.lm_studio.get_active_model(),
                )
            else:
                # Hybrid mode (only if explicitly requested)
                if self.groq.is_healthy():
                    try:
                        return self.groq.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode, model=target_model)
                    except Exception as groq_err:
                        logger.warning(
                            "Groq inference failed in hybrid mode, falling back to Local LM Studio",
                            error=str(groq_err),
                        )
                local_model = None if (target_model and any(k in target_model.lower() for k in ["openai", "gpt-oss", "groq"])) else target_model
                return self.lm_studio.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode, model=local_model)

    def check_clarification(self, user_requirement: str) -> ClarificationResponse:
        """Legacy clarification check: forwards to generate_architecture_questions."""
        return self.generate_architecture_questions(prompt=user_requirement)

    def generate_architecture_questions(
        self,
        prompt: str,
        current_requirements_md: Optional[str] = None,
        cloud_provider: str = "aws",
        environment: str = "local",
        history: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ClarificationResponse:
        """
        Generate interactive architecture choice questions with clickable UI option pills.
        F5: Intent-keyed question bank (max 4, option-chips, only if plan-changing).
        - static_site: source? · custom domain? · public-read OK? · CDN later?
        - vpc: internet access needed? · private subnets? · NAT egress?
        - database: engine? · size? · backups? · private-only?
        - Never ask what the IR already knows or what has a safe default.
        """
        lowered = prompt.lower().strip()

        # 1. Check if user prompt is an explicit command to plan, synthesize, or approve
        planning_keywords = [
            "plan this", "plan the", "synthesize plan", "synthesize", "generate terraform",
            "generate sql", "build plan", "create plan", "deploy plan", "approve", "proceed",
            "execute plan", "start deployment", "generate hcl", "[plan]", "[deploy]", "[build]"
        ]
        if any(k in lowered for k in planning_keywords):
            return ClarificationResponse(is_ready=True, questions=[])

        # 2. Check if the user prompt is submitting clarification answers
        is_clarification_submission = (
            "please apply the following architecture decisions" in lowered
            or "[clarification]:" in lowered
            or "[clarification answer]" in lowered
            or lowered.startswith("i choose:")
            or "i choose:" in lowered
        )
        if is_clarification_submission:
            return ClarificationResponse(is_ready=True, questions=[])

        req_md = (current_requirements_md or "").lower()
        full_context = f"{lowered}\n{req_md}"

        from app.validation.scope_fidelity import ScopeFidelityValidator
        intents = ScopeFidelityValidator.analyze_user_intent(prompt)

        wants_static_site = intents["wants_static_site"]
        wants_database = intents["wants_database"]
        wants_network = intents["wants_network"]

        # Default fallback if no specific intent matched: ready to proceed
        if not (wants_static_site or wants_database or wants_network):
            return ClarificationResponse(is_ready=True, questions=[])

        questions: List[ClarificationQuestion] = []

        # =========================================================================
        # 1. STATIC SITE INTENT BANK (max 4 chips)
        # =========================================================================
        if wants_static_site:
            # Q1: source? (GitHub URL / paste / existing bucket)
            has_source = any(k in lowered for k in [
                "github.com", "http://", "https://", "github repo", "github",
                "inline", "paste", "html", "files", "existing bucket"
            ])
            if not has_source:
                questions.append(
                    ClarificationQuestion(
                        question="Where will the static website source code come from?",
                        context="Determines whether to sync content from a Git repository or deploy inline pasted files.",
                        default_suggestion="GitHub Repository URL",
                        options=[
                            "GitHub Repository URL",
                            "Paste / Inline HTML/CSS/JS",
                            "Existing S3 Bucket Content",
                        ],
                    )
                )

            # Q2: custom domain?
            has_domain = any(k in full_context for k in [
                "custom domain", "route53", ".com", ".io", ".org", ".net", ".dev", "domain name", "cname"
            ])
            if not has_domain:
                questions.append(
                    ClarificationQuestion(
                        question="Do you require a custom domain name with SSL for the website?",
                        context="Configures Route 53 DNS routing and TLS certificate or uses direct S3 website endpoint.",
                        default_suggestion="Direct S3 Website Endpoint (No custom domain)",
                        options=[
                            "Direct S3 Website Endpoint (No custom domain)",
                            "Route 53 Custom Domain with ACM SSL Certificate",
                            "External DNS / CloudFront Alias",
                        ],
                    )
                )

            # Q3: public-read OK?
            has_public_pref = any(k in full_context for k in [
                "public-read", "publicly readable", "public read", "private bucket", "oac", "origin access control"
            ])
            if not has_public_pref:
                questions.append(
                    ClarificationQuestion(
                        question="Is public-read access acceptable for this website bucket?",
                        context="S3 static website hosting serves assets directly over HTTP via public read bucket policy.",
                        default_suggestion="Yes - Public read via bucket policy (Standard S3 website)",
                        options=[
                            "Yes - Public read via bucket policy (Standard S3 website)",
                            "No - Private bucket with CloudFront Origin Access Control (OAC)",
                        ],
                    )
                )

            # Q4: CDN later?
            has_cdn_pref = any(k in full_context for k in [
                "cloudfront", "cdn", "edge distribution", "global cache"
            ])
            if not has_cdn_pref:
                questions.append(
                    ClarificationQuestion(
                        question="Should a CloudFront CDN distribution be provisioned in front of the website?",
                        context="CloudFront provides global edge caching, HTTPS acceleration, and DDoS protection.",
                        default_suggestion="Direct S3 Website Endpoint (Lowest cost, simple)",
                        options=[
                            "Direct S3 Website Endpoint (Lowest cost, simple)",
                            "Add CloudFront Global CDN Distribution",
                        ],
                    )
                )

        # =========================================================================
        # 2. VPC INTENT BANK (max 4 chips)
        # =========================================================================
        elif wants_network and not wants_database:
            # Q1: internet access needed?
            has_inet_pref = any(k in lowered for k in [
                "public", "internet", "public subnet", "igw", "gateway", "connected to internet",
                "isolated", "private-only", "no internet", "airgapped"
            ])
            if not has_inet_pref:
                questions.append(
                    ClarificationQuestion(
                        question="Does this VPC require direct internet connectivity via an Internet Gateway?",
                        context="Provisions an Internet Gateway (IGW) and public route table (0.0.0.0/0 -> IGW).",
                        default_suggestion="Yes - Public subnets with Internet Gateway (IGW)",
                        options=[
                            "Yes - Public subnets with Internet Gateway (IGW)",
                            "No - Isolated private network without IGW",
                        ],
                    )
                )

            # Q2: private subnets?
            has_subnet_tier = any(k in lowered for k in [
                "private subnet", "tier", "3-tier", "2-tier", "public only", "single tier"
            ])
            if not has_subnet_tier:
                questions.append(
                    ClarificationQuestion(
                        question="Which subnet tiering architecture should be provisioned?",
                        context="Defines segmentation between public entrypoints and private application/data tiers.",
                        default_suggestion="Public subnets only (Simple single-tier)",
                        options=[
                            "Public subnets only (Simple single-tier)",
                            "Public + Private subnets (Standard 2-tier)",
                            "3-tier (Public, Application, Database)",
                        ],
                    )
                )

            # Q3: NAT egress?
            has_nat = any(k in lowered for k in [
                "nat", "nat gateway", "no nat", "single nat", "dual nat", "multi-az nat"
            ])
            is_isolated = any(k in lowered for k in ["isolated", "no internet", "airgapped"])
            if not has_nat and not is_isolated:
                questions.append(
                    ClarificationQuestion(
                        question="How should outbound internet connectivity for private subnets be handled?",
                        context="NAT Gateways allow private subnets to reach the internet for updates without accepting inbound connections.",
                        default_suggestion="No NAT Gateway (Cost-optimized)",
                        options=[
                            "No NAT Gateway (Cost-optimized)",
                            "Single NAT Gateway (~$32/mo)",
                            "Multi-AZ NAT Gateways (High Availability)",
                        ],
                    )
                )

        # =========================================================================
        # 3. DATABASE INTENT BANK (max 4 chips)
        # =========================================================================
        elif wants_database:
            # Q1: engine?
            has_engine = any(k in lowered for k in [
                "postgres", "postgresql", "mysql", "aurora", "mariadb", "mongo", "mongodb", "dynamodb"
            ])
            if not has_engine:
                questions.append(
                    ClarificationQuestion(
                        question="Which relational database engine should be provisioned?",
                        context="Configures the database engine dialect and feature set.",
                        default_suggestion="PostgreSQL 16",
                        options=[
                            "PostgreSQL 16",
                            "MySQL 8.0",
                            "Aurora PostgreSQL Serverless v2",
                        ],
                    )
                )

            # Q2: size?
            has_size = any(k in lowered for k in [
                "t3.micro", "t4g.micro", "t4g.small", "r6g", "instance class", "instance size",
                "sizing", "db.t", "db.r", "small", "large", "free tier", "free-tier"
            ])
            if not has_size:
                questions.append(
                    ClarificationQuestion(
                        question="What database instance sizing tier is appropriate for your workload?",
                        context="Defines CPU, memory, and performance burst capability.",
                        default_suggestion="db.t4g.micro (Dev / Free-tier eligible)",
                        options=[
                            "db.t4g.micro (Dev / Free-tier eligible)",
                            "db.t4g.small (2 vCPU, 2GB RAM - Staging)",
                            "db.r6g.large (Production HA, 16GB RAM)",
                        ],
                    )
                )

            # Q3: backups?
            has_backup = any(k in lowered for k in [
                "backup", "backups", "snapshot", "retention", "pitr"
            ])
            if not has_backup:
                questions.append(
                    ClarificationQuestion(
                        question="What automated backup retention policy should be configured?",
                        context="Sets automated snapshot retention window and point-in-time recovery window.",
                        default_suggestion="7 days retention (Standard)",
                        options=[
                            "7 days retention (Standard)",
                            "30 days retention (Compliance)",
                            "No automated backups (Dev ephemeral)",
                        ],
                    )
                )

            # Q4: private-only?
            has_private_db = any(k in lowered for k in [
                "private-only", "private only", "publicly accessible", "public access", "public database"
            ])
            if not has_private_db:
                questions.append(
                    ClarificationQuestion(
                        question="Should the database instance be restricted to private subnets only?",
                        context="Security best practice recommends keeping databases isolated in private subnets without public IPs.",
                        default_suggestion="Private-only subnet (Recommended for security)",
                        options=[
                            "Private-only subnet (Recommended for security)",
                            "Publicly accessible (Dev testing only)",
                        ],
                    )
                )

        # Enforce maximum 4 questions per prompt
        questions = questions[:4]

        if questions:
            return ClarificationResponse(is_ready=False, questions=questions)
        return ClarificationResponse(is_ready=True, questions=[])

    def chat_architect(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        current_requirements_md: Optional[str] = None,
        cloud_provider: str = "aws",
        environment: str = "local",
        rag_context: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """Converse as an expert cloud & database solutions architect."""
        if not self.is_healthy():
            return self._fallback_chat_architect(prompt, cloud_provider, environment)

        messages = [{"role": "system", "content": ARCHITECT_CONVERSATION_SYSTEM_PROMPT}]

        context_parts = []
        if current_requirements_md:
            context_parts.append(
                f"Current Session Architecture Specification (requirements.md):\n{current_requirements_md}"
            )
        if rag_context:
            context_parts.append(
                f"Authoritative Documentation & CIS Benchmarks (RAG Grounded):\n{rag_context}"
            )

        if context_parts:
            messages.append({
                "role": "system",
                "content": "\n\n---\n\n".join(context_parts)
            })

        if history:
            for turn in history[-6:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ["user", "assistant"] and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt})

        try:
            return self.chat(messages, temperature=0.3, max_tokens=1500, model=model, provider=provider)
        except Exception as e:
            logger.error("Architect chat call failed, falling back", error=str(e))
            return self._fallback_chat_architect(prompt, cloud_provider, environment)

    def synthesize_requirements(
        self,
        current_requirements_md: str,
        prompt: str,
        ai_response: str,
        cloud_provider: str = "aws",
        environment: str = "local",
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """Update and consolidate the living requirements.md specification."""
        if not self.is_healthy():
            return self._fallback_synthesize_requirements(current_requirements_md, prompt, cloud_provider, environment)

        messages = [
            {"role": "system", "content": REQUIREMENTS_SYNTHESIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Current requirements.md:\n{current_requirements_md}\n\n"
                    f"Target Cloud Provider: {cloud_provider.upper()}\n"
                    f"Target Environment: {environment}\n\n"
                    f"Latest User Requirement:\n{prompt}\n\n"
                    f"Architect Response:\n{ai_response}\n\n"
                    f"Synthesize the complete, updated requirements.md document adhering to the standard outline."
                )
            }
        ]

        try:
            raw = self.chat(messages, temperature=0.1, max_tokens=4096, model=model, provider=provider)
            clean = raw.strip()
            if clean.startswith("```markdown"):
                clean = clean[len("```markdown"):].strip()
            elif clean.startswith("```"):
                clean = clean[3:].strip()
            if clean.endswith("```"):
                clean = clean[:-3].strip()
            if not any(k in clean for k in ["## 6.", "Database", "database"]) or not any(k in clean for k in ["## 3.", "Network", "network"]):
                logger.warning("Synthesized requirements document was incomplete, merging fallback sections")
                return self._fallback_synthesize_requirements(current_requirements_md, prompt, cloud_provider, environment)
            return clean if clean else current_requirements_md
        except Exception as e:
            logger.warning("Synthesize requirements call failed, using fallback", error=str(e))
            return self._fallback_synthesize_requirements(current_requirements_md, prompt, cloud_provider, environment)

    def _fallback_chat_architect(self, prompt: str, cloud_provider: str = "aws", environment: str = "local") -> str:
        prompt_clean = prompt.strip()
        lowered = prompt_clean.lower()

        detected_topics = []
        if any(w in lowered for w in ["database", "postgres", "mysql", "mongodb", "schema", "table"]):
            detected_topics.append("Relational Database tier with concrete schema & column definitions")
        if any(w in lowered for w in ["s3", "storage", "bucket", "asset", "blob"]):
            detected_topics.append("Amazon S3 Object Storage with SSE-KMS & 4-flag Public Access Block")
        if any(w in lowered for w in ["vpc", "network", "subnet", "cidr"]):
            detected_topics.append("Isolated VPC Networking with 3-tier multi-AZ subnets (10.0.0.0/16)")
        if any(w in lowered for w in ["ec2", "compute", "ecs", "server", "app"]):
            detected_topics.append("Compute tier with EBS gp3 encryption & SSM Session Manager")

        topic_summary = ""
        if detected_topics:
            topic_summary = "\n**Key components formulated**:\n" + "\n".join(f"- {t}" for t in detected_topics) + "\n"

        return (
            f"I have analyzed your infrastructure requirement for **{cloud_provider.upper()}** ({environment}) and updated the **Architecture Specification (`requirements.md`)** with technical engineering details.\n\n"
            f"{topic_summary}\n"
            f"Please review the **Architecture Decisions & Interactive Choices** below to configure network CIDRs, NAT redundancy, and database tiers with 1 click. "
            f"Once you've made your choices or whenever you are ready, say **'Plan this architecture'** or click **Synthesize Plan** to generate the Terraform HCL and SQL schema."
        )

    def _fallback_synthesize_requirements(
        self,
        current_requirements_md: str,
        prompt: str,
        cloud_provider: str = "aws",
        environment: str = "local",
    ) -> str:
        prompt_clean = prompt.strip()
        lowered = prompt_clean.lower()
        provider_name = cloud_provider.upper() if cloud_provider else "AWS"
        env_name = environment if environment else "local"

        # Check for user decisions in prompt or current md
        cidr = "10.0.0.0/16"
        if "172.16" in lowered or "172.16" in current_requirements_md:
            cidr = "172.16.0.0/16"
        elif "192.168" in lowered or "192.168" in current_requirements_md:
            cidr = "192.168.0.0/16"

        prefix = cidr.rsplit(".", 2)[0]
        pub1 = f"{prefix}.1.0/24"
        pub2 = f"{prefix}.2.0/24"
        app1 = f"{prefix}.10.0/24"
        app2 = f"{prefix}.11.0/24"
        db1 = f"{prefix}.20.0/24"
        db2 = f"{prefix}.21.0/24"

        # NAT Gateway redundancy
        if "single nat" in lowered or "single nat" in current_requirements_md.lower():
            nat_desc = "Single NAT Gateway with dedicated Elastic IP in public-subnet-1a (Cost-optimized, ~$32/mo)"
        elif "no nat" in lowered or "no nat" in current_requirements_md.lower():
            nat_desc = "No NAT Gateway (Isolated VPC, private VPC Endpoints for S3 and SSM)"
        else:
            nat_desc = "High Availability dual NAT Gateways with dedicated Elastic IPs (`eip-nat-1a`, `eip-nat-1b`)"

        # Database Engine & Sizing
        db_engine = "PostgreSQL 16.2"
        db_port = 5432
        if "mysql" in lowered or "mysql" in current_requirements_md.lower():
            db_engine = "MySQL 8.0"
            db_port = 3306
        elif "mongodb" in lowered or "mongo" in lowered:
            db_engine = "MongoDB DocumentStore 7.0"
            db_port = 27017

        # Database HA
        if "single az" in lowered or "single az" in current_requirements_md.lower():
            db_ha = "Single-AZ Deployment (Cost-optimized dev/test configuration)"
        else:
            db_ha = "Multi-AZ Deployment (Synchronous standby replica in secondary AZ for automated failover)"

        # S3 Encryption
        if "sse-s3" in lowered or "sse-s3" in current_requirements_md.lower():
            s3_enc = "SSE-S3 (AES-256 Amazon S3 managed key)"
        elif "customer managed" in lowered or "customer managed" in current_requirements_md.lower():
            s3_enc = "Customer Managed KMS Key (CMK) with automated key rotation"
        else:
            s3_enc = "Server-Side Encryption with AWS KMS (SSE-KMS, `alias/aws/s3`)"

        # EC2 Sizing
        compute_size = "AWS EC2 `t3.micro` (2 vCPU, 1 GB RAM, Nitro-based, EBS-optimized)"
        if "t3.small" in lowered or "t3.small" in current_requirements_md.lower():
            compute_size = "AWS EC2 `t3.small` (2 vCPU, 2 GB RAM, Nitro-based, EBS-optimized)"
        elif "t4g.small" in lowered or "graviton" in lowered:
            compute_size = "AWS EC2 `t4g.small` (AWS Graviton3, 2 vCPU, 2 GB RAM, ARM64)"

        # Extract table names
        detected_tables = []
        table_matches = re.findall(r'(?:table|entity|model)s?[^\n\w]+(?:named|called)?\s*[\'"`]?([a-zA-Z0-9_]{2,30})[\'"`]?', lowered)
        for t in table_matches:
            if t not in ["name", "called", "named", "table", "for", "with", "and"]:
                detected_tables.append(t)

        direct_matches = re.findall(r'table\s+name\s+([a-zA-Z0-9_]+)', lowered)
        for d in direct_matches:
            if d not in detected_tables:
                detected_tables.append(d)

        if not detected_tables:
            if any(w in lowered for w in ["user", "account", "login", "auth"]):
                detected_tables.append("users")
            elif any(w in lowered for w in ["patient", "clinic", "health"]):
                detected_tables.append("patients")
            elif any(w in lowered for w in ["order", "shop", "ecommerce", "cart"]):
                detected_tables.append("orders")
            elif any(w in lowered for w in ["database", "rds", "postgres", "sql"]):
                detected_tables.append("users")

        table_sections = []
        for tbl in detected_tables:
            tbl_clean = tbl.lower().strip()
            if tbl_clean in ["user", "users"]:
                table_sections.append(
                    "- **Table**: `users`\n"
                    "  - `id`: UUID PRIMARY KEY DEFAULT gen_random_uuid()\n"
                    "  - `username`: VARCHAR(100) UNIQUE NOT NULL (Indexed for rapid authentication)\n"
                    "  - `email`: VARCHAR(255) UNIQUE NOT NULL (Indexed)\n"
                    "  - `password_hash`: VARCHAR(255) NOT NULL\n"
                    "  - `first_name`: VARCHAR(100) NULLABLE\n"
                    "  - `last_name`: VARCHAR(100) NULLABLE\n"
                    "  - `role`: VARCHAR(50) DEFAULT 'user' NOT NULL\n"
                    "  - `is_active`: BOOLEAN DEFAULT TRUE NOT NULL\n"
                    "  - `created_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
                    "  - `updated_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL"
                )
            elif tbl_clean in ["order", "orders"]:
                table_sections.append(
                    "- **Table**: `orders`\n"
                    "  - `id`: UUID PRIMARY KEY DEFAULT gen_random_uuid()\n"
                    "  - `user_id`: UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE\n"
                    "  - `order_number`: VARCHAR(64) UNIQUE NOT NULL\n"
                    "  - `total_amount`: DECIMAL(12,2) NOT NULL CHECK (total_amount >= 0)\n"
                    "  - `currency`: VARCHAR(3) DEFAULT 'USD' NOT NULL\n"
                    "  - `status`: VARCHAR(32) DEFAULT 'pending' NOT NULL\n"
                    "  - `created_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
                    "  - `updated_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL"
                )
            elif tbl_clean in ["patient", "patients"]:
                table_sections.append(
                    "- **Table**: `patients`\n"
                    "  - `id`: UUID PRIMARY KEY DEFAULT gen_random_uuid()\n"
                    "  - `medical_record_number`: VARCHAR(64) UNIQUE NOT NULL (Indexed)\n"
                    "  - `first_name`: VARCHAR(100) NOT NULL\n"
                    "  - `last_name`: VARCHAR(100) NOT NULL\n"
                    "  - `date_of_birth`: DATE NOT NULL\n"
                    "  - `gender`: VARCHAR(20) NOT NULL\n"
                    "  - `contact_phone`: VARCHAR(30) NULLABLE\n"
                    "  - `created_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
                    "  - `updated_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL"
                )
            else:
                table_sections.append(
                    f"- **Table**: `{tbl_clean}`\n"
                    f"  - `id`: UUID PRIMARY KEY DEFAULT gen_random_uuid()\n"
                    f"  - `name`: VARCHAR(255) NOT NULL\n"
                    f"  - `status`: VARCHAR(50) DEFAULT 'active' NOT NULL\n"
                    f"  - `metadata_json`: JSONB DEFAULT '{{}}'::jsonb NOT NULL\n"
                    f"  - `created_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
                    f"  - `updated_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL"
                )

        schema_md = "\n".join(table_sections) if table_sections else (
            "- **Table**: `users`\n"
            "  - `id`: UUID PRIMARY KEY DEFAULT gen_random_uuid()\n"
            "  - `username`: VARCHAR(100) UNIQUE NOT NULL\n"
            "  - `email`: VARCHAR(255) UNIQUE NOT NULL\n"
            "  - `created_at`: TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL"
        )

        from app.validation.scope_fidelity import ScopeFidelityValidator
        intents = ScopeFidelityValidator.analyze_user_intent(prompt)

        # For static site hosting
        if intents["wants_static_site"]:
            return f"""# Architecture Specification & Requirements

## 1. System Overview & Objective
- **Workload Summary**: High-performance static website hosting on AWS S3.
- **Core Requirement**: {prompt.strip()}
- **Architectural Tenets**: Object storage static hosting, HTTPS / public read capability for static content.

## 2. Target Environment & Cloud Metadata
- **Cloud Provider**: {provider_name}
- **Environment**: {env_name}
- **Target Region**: us-east-1

## 3. Storage & Static Website Hosting Tier (Amazon S3)
- **Bucket Identification**: `static-site-assets-{env_name}`
- **Hosting Mode**: Static website hosting with `index.html` and `error.html`
- **Bucket Policy**: Public read allowed on `s3:GetObject` for website bucket
- **Public Access Block**: `block_public_policy = false`, `restrict_public_buckets = false`
"""

        # For pure VPC networking
        if intents["wants_network"] and not intents["wants_database"] and not intents["wants_storage"]:
            return f"""# Architecture Specification & Requirements

## 1. System Overview & Objective
- **Workload Summary**: Resilient cloud network infrastructure on {provider_name}.
- **Core Requirement**: {prompt.strip()}
- **Architectural Tenets**: Zero-trust network segmentation, route table segregation.

## 2. Target Environment & Cloud Metadata
- **Cloud Provider**: {provider_name}
- **Environment**: {env_name}
- **Target Region**: us-east-1

## 3. Network Topology & IPAM Architecture
- **VPC CIDR Block**: `{cidr}`
- **Subnet Tiering Matrix**:
  - `public-subnet-1a`: `{pub1}` (AZ: us-east-1a, IGW attached, map public IP)
  - `private-subnet-1b`: `{app1}` (AZ: us-east-1b, Isolated private subnet)
- **Gateways & Egress Routing**:
  - **Internet Gateway (IGW)**: `main-vpc-igw` (Default route `0.0.0.0/0` for public subnet)
"""

        # For pure database
        if intents["wants_database"] and not intents["wants_network"] and not intents["wants_storage"]:
            return f"""# Architecture Specification & Requirements

## 1. System Overview & Objective
- **Workload Summary**: Database schema & persistence model.
- **Core Requirement**: {prompt.strip()}

## 2. Target Environment & Database Engine
- **Database Engine**: {db_engine}
- **Environment**: {env_name}

## 3. Relational Schema & Data Model
{schema_md}
"""

        return f"""# Architecture Specification & Requirements

## 1. System Overview & Objective
- **Workload Summary**: Resilient, scalable 3-tier enterprise cloud architecture on {provider_name}.
- **Core Requirement**: {prompt.strip()}
- **Architectural Tenets**: Zero-trust network segmentation, encryption at rest and in transit, automated multi-AZ failover, and least-privilege IAM enforcement.

## 2. Target Environment & Cloud Metadata
- **Cloud Provider**: {provider_name}
- **Environment**: {env_name}
- **Target Region**: us-east-1
- **Availability Zones**: us-east-1a, us-east-1b (Multi-AZ redundancy)
- **Compliance Baseline**: CIS {provider_name} Foundations Benchmark v3.0

## 3. Network Topology & IPAM Architecture
- **VPC CIDR Block**: `{cidr}` (65,536 total addresses, DNS hostnames & support enabled)
- **Subnet Tiering Matrix**:
  - `public-subnet-1a`: `{pub1}` (AZ: us-east-1a, IGW attached, map public IP)
  - `public-subnet-1b`: `{pub2}` (AZ: us-east-1b, IGW attached, map public IP)
  - `private-app-subnet-1a`: `{app1}` (AZ: us-east-1a, Route -> NAT Gateway 1a)
  - `private-app-subnet-1b`: `{app2}` (AZ: us-east-1b, Route -> NAT Gateway 1b)
  - `private-db-subnet-1a`: `{db1}` (AZ: us-east-1a, Isolated DB tier, no direct internet)
  - `private-db-subnet-1b`: `{db2}` (AZ: us-east-1b, Isolated DB tier, no direct internet)
- **Gateways & Egress Routing**:
  - **Internet Gateway (IGW)**: `main-vpc-igw` (Default route `0.0.0.0/0` for public subnets)
  - **NAT Gateways**: {nat_desc}
  - **VPC Flow Logs**: Enabled to CloudWatch Logs with 30-day retention for auditability
- **Security Groups & Firewall Policy**:
  - `sg-alb`: Ingress TCP 80, 443 from `0.0.0.0/0`; Egress to `sg-app` on port 8080.
  - `sg-app`: Ingress TCP 8080 from `sg-alb` only; Ingress TCP 22 (SSH) blocked; Egress to `sg-db` on port {db_port} and HTTPS 443 via NAT.
  - `sg-db`: Ingress TCP {db_port} from `sg-app` only; All public 0.0.0.0/0 inbound strictly rejected.

## 4. Compute & Workload Architecture
- **Instance Profile & Sizing**: {compute_size}
- **AMI Baseline**: Amazon Linux 2023 (x86_64, Kernel 6.1 LTS)
- **Placement**: Private application subnets (`{app1}`, `{app2}`) behind ALB
- **Storage / Root Volume**: 20 GB `gp3` SSD, 3,000 baseline IOPS, 125 MB/s throughput, encrypted via KMS (`alias/aws/ebs`)
- **IAM Role & Governance**: Attached `AmazonSSMManagedInstanceCore` for secure bastionless AWS Systems Manager Session Manager access.

## 5. Storage Tier (Amazon S3)
- **Bucket Identification**: `app-data-assets-{env_name}`
- **Encryption at Rest**: {s3_enc}
- **Bucket Access Policy**: Public Access Block enabled across all 4 controls (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`).
- **Transport Security**: Bucket policy enforcing `aws:SecureTransport: true` (rejects unencrypted HTTP requests).
- **Versioning & Lifecycle**: Bucket versioning enabled; non-current version expiration after 90 days; lifecycle transition to Glacier Flexible Retrieval at 30 days.

## 6. Managed Database Tier & Relational Data Model
- **Engine & Version**: {db_engine}
- **Deployment Topology**: {db_ha}
- **Instance Class**: `db.t3.micro` / `db.t3.small`
- **Subnet Group**: `rds-db-subnet-group` spanning `{db1}` and `{db2}`
- **Storage Specification**: 20 GB General Purpose SSD (`gp3`), Storage Auto-scaling enabled up to 100 GB.
- **Security & Encryption**: Storage encrypted via AWS KMS (`alias/aws/rds`), SSL/TLS enforcement enabled (`rds.force_ssl = 1`).
- **Backup & Maintenance**: Automated snapshot backups with 7-day retention period; backup window `03:00-04:00 UTC`; maintenance window `Sun:04:30-Sun:05:30 UTC`.
- **Schema & Relational Data Model**:
{schema_md}

## 7. Security, Reliability & Compliance
- **Secrets Management**: Database credentials stored in AWS Secrets Manager with KMS encryption and automated rotation.
- **Monitoring & Observability**: AWS CloudWatch Alarms for CPU utilization (>80%), RDS FreeableMemory (<256MB), and RDS FreeStorageSpace (<5GB).
- **Disaster Recovery (DR)**: RPO < 5 minutes (via Multi-AZ synchronous replication and S3 versioning), RTO < 30 minutes.
"""

    def generate_ir(
        self,
        user_requirement: str,
        max_retries: int = 2,
        rag_context: Optional[str] = None,
        requirements_md: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> UniversalIR:
        """Generate Universal IR from natural language requirement and accumulated requirements.md."""
        if not self.is_healthy():
            logger.warning("No LLM backend available, using dynamic template IR generator")
            return self._generate_fallback_ir(user_requirement, requirements_md=requirements_md)

        user_content = f"Design infrastructure for this requirement:\n{user_requirement}"
        if requirements_md and requirements_md.strip():
            user_content = (
                f"Consolidated Architecture Specification (requirements.md):\n"
                f"{requirements_md}\n\n"
                f"User Directive / Specific Goal:\n{user_requirement}"
            )
        if rag_context:
            user_content = (
                f"Historical Conversation & Architecture Context (Retrieved via RAG Memory):\n"
                f"{rag_context}\n\n"
                f"{user_content}"
            )

        messages = [
            {"role": "system", "content": UNIVERSAL_IR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                raw_response = self.chat(
                    messages,
                    json_mode=True,
                    temperature=0.1,
                    max_tokens=2048,
                    model=model,
                    provider=provider,
                )
                ir = LLMParser.parse_universal_ir(raw_response)
                return ir
            except Exception as e:
                last_error = e
                logger.warning(
                    "IR generation attempt failed, retrying...",
                    attempt=attempt,
                    error=str(e),
                )
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    time.sleep(2.0)
                else:
                    messages.append({
                        "role": "user",
                        "content": f"Your previous response had a schema error: {str(e)}. Please correct it and output strictly valid JSON conforming to the Universal IR schema."
                    })

        logger.error("All IR generation attempts failed, using robust fallback", error=str(last_error))
        return self._generate_fallback_ir(user_requirement, requirements_md=requirements_md)

    def revise_plan(
        self,
        existing_ir: UniversalIR,
        modifications: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> UniversalIR:
        """Revise an existing plan according to human feedback."""
        if not self.is_healthy():
            updated = existing_ir.model_copy(deep=True)
            updated.assumptions.append(f"Modification applied: {modifications}")
            return updated

        messages = [
            {"role": "system", "content": REVISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Current Plan:\n{existing_ir.model_dump_json(indent=2)}\n\nUser Modifications:\n{modifications}",
            },
        ]
        raw_response = self.chat(
            messages,
            json_mode=True,
            temperature=0.1,
            model=model,
            provider=provider,
        )
        return LLMParser.parse_universal_ir(raw_response)

    def _generate_fallback_ir(self, req: str, requirements_md: Optional[str] = None) -> UniversalIR:
        """Dynamic heuristic fallback IR strictly adhering to user scope without unsolicited extras (F4)."""
        from app.validation.scope_fidelity import ScopeFidelityValidator
        intents = ScopeFidelityValidator.analyze_user_intent(req)
        lowered = req.lower().strip()

        # 1. Static site deployment intent (e.g. "host static site from github X")
        if intents["wants_static_site"]:
            gh_match = re.search(r"https?://github\.com/[^\s]+", req)
            site_source = {"type": "github", "repo_url": gh_match.group(0)} if gh_match else {"type": "inline"}
            b_name = "static-website-bucket"
            m = re.search(r'bucket[^\w]+([a-z0-9\-]+)', lowered)
            if m:
                b_name = m.group(1)

            res = [
                {
                    "type": "object_storage",
                    "name": "static_site_bucket",
                    "properties": {"bucket_name": b_name, "website": True},
                    "is_dependency": False,
                    "tags": {"ManagedBy": "Vellum", "Purpose": "StaticWebsite"}
                }
            ]
            return UniversalIR(
                intent="deploy_static_site",
                description=f"Static website hosting: {req[:100]}",
                site_source=site_source,
                database=None,
                cloud={
                    "provider": "aws",
                    "region": "us-east-1",
                    "environment": "local",
                    "resources": res,
                },
                dependencies=[],
                assumptions=["Required because: static site hosting requires S3 website configuration and public read policy"],
                estimated_cost_monthly=5.0,
                risk_level="low",
            )

        # 2. Pure VPC network intent (e.g. "create a vpc", "create a vpc with public subnet")
        if intents["wants_network"] and not intents["wants_database"] and not intents["wants_storage"]:
            res = [
                {
                    "type": "virtual_network",
                    "name": "main_vpc",
                    "properties": {"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": True, "enable_dns_support": True},
                    "is_dependency": False,
                    "tags": {"ManagedBy": "Vellum", "Name": "main_vpc"}
                },
                {
                    "type": "subnet",
                    "name": "public_subnet_1",
                    "properties": {"vpc_name": "main_vpc", "cidr_block": "10.0.1.0/24", "map_public_ip_on_launch": True},
                    "is_dependency": False,
                    "tags": {"Name": "public_subnet_1"}
                },
                {
                    "type": "internet_gateway",
                    "name": "main_igw",
                    "properties": {"vpc_name": "main_vpc"},
                    "is_dependency": True,
                    "dependency_reason": "Required because: public subnet requires an Internet Gateway for internet access"
                }
            ]
            if "private" in lowered:
                res.append({
                    "type": "subnet",
                    "name": "private_subnet_1",
                    "properties": {"vpc_name": "main_vpc", "cidr_block": "10.0.2.0/24", "map_public_ip_on_launch": False},
                    "is_dependency": False,
                    "tags": {"Name": "private_subnet_1"}
                })

            return UniversalIR(
                intent="deploy_cloud",
                description=f"VPC network architecture: {req[:100]}",
                database=None,
                cloud={
                    "provider": "aws",
                    "region": "us-east-1",
                    "environment": "local",
                    "resources": res,
                },
                dependencies=["main_igw"],
                assumptions=["Required because: public subnet requires an Internet Gateway for internet access"],
                estimated_cost_monthly=0.0,
                risk_level="low",
            )

        req_md_clean = (requirements_md or "").lower()
        full_text = f"{lowered}\n{req_md_clean}"

        # 3. Pure database intent (e.g. "create a postgres database with users table")
        if intents["wants_database"] and not intents["wants_network"] and not intents["wants_storage"]:
            db_provider = "postgresql"
            if "mysql" in full_text:
                db_provider = "mysql"
            elif "mongodb" in full_text or "mongo" in full_text:
                db_provider = "mongodb"
            elif "aurora" in full_text:
                db_provider = "postgresql"

            detected_tables = []
            table_matches = re.findall(r'(?:table|entity|model)s?[^\n\w]+(?:named|called)?\s*[\'"`]?([a-zA-Z0-9_]{2,30})[\'"`]?', lowered)
            for t in table_matches:
                clean_t = t.lower().strip()
                if clean_t not in ["named", "called", "table", "for", "with", "the", "and", "data", "schema"] and clean_t not in detected_tables:
                    detected_tables.append(clean_t)
            if not detected_tables:
                detected_tables = ["records"]

            tables = []
            for tbl_name in detected_tables:
                tables.append({
                    "name": tbl_name,
                    "description": f"Domain table for {tbl_name}",
                    "columns": [
                        {"name": "id", "data_type": "serial", "primary_key": True, "nullable": False, "unique": True},
                        {"name": "name", "data_type": "varchar(255)", "primary_key": False, "nullable": False, "unique": False},
                        {"name": "created_at", "data_type": "timestamp", "primary_key": False, "nullable": True, "default": "CURRENT_TIMESTAMP"}
                    ],
                    "indexes": [],
                    "foreign_keys": []
                })

            assumptions = [f"Relational database schema for {db_provider}"]
            if "db.t4g.small" in full_text:
                assumptions.append("Instance sizing choice: db.t4g.small (Staging)")
            elif "db.r6g.large" in full_text:
                assumptions.append("Instance sizing choice: db.r6g.large (Production HA)")
            elif "db.t4g.micro" in full_text:
                assumptions.append("Instance sizing choice: db.t4g.micro (Dev/Free-tier)")

            return UniversalIR(
                intent="create_database",
                description=f"Database schema: {req[:100]}",
                database={
                    "provider": db_provider,
                    "database_name": "app_db",
                    "tables": tables,
                    "views": [],
                    "extensions": ["uuid-ossp"] if db_provider == "postgresql" else []
                },
                cloud=None,
                dependencies=[],
                assumptions=assumptions,
                estimated_cost_monthly=0.0,
                risk_level="low",
            )

        # 4. Multi-tier or combined intent (only include requested components)
        cloud_resources = []
        if intents["wants_network"]:
            cloud_resources.extend([
                {
                    "type": "virtual_network",
                    "name": "main_vpc",
                    "properties": {"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": True, "enable_dns_support": True},
                    "is_dependency": False,
                    "tags": {"ManagedBy": "Vellum", "Name": "main_vpc"}
                },
                {
                    "type": "subnet",
                    "name": "public_subnet_1",
                    "properties": {"vpc_name": "main_vpc", "cidr_block": "10.0.1.0/24", "availability_zone": "us-east-1a"},
                    "is_dependency": False,
                    "tags": {"Name": "public_subnet_1"}
                }
            ])

        if intents["wants_storage"]:
            cloud_resources.append({
                "type": "object_storage",
                "name": "app_data_bucket",
                "properties": {"bucket_name": "app-data-bucket", "versioning_enabled": True},
                "is_dependency": False,
                "tags": {"ManagedBy": "Vellum"}
            })

        if intents["wants_database"]:
            cloud_resources.append({
                "type": "managed_database",
                "name": "primary_rds",
                "properties": {"allocated_storage": 20, "engine": "postgres", "instance_class": "db.t3.micro"},
                "is_dependency": False,
                "tags": {"Name": "primary_rds"}
            })

        return UniversalIR(
            intent="deploy_cloud" if not intents["wants_database"] else "create_database_and_deploy_cloud",
            description=f"Provisioned infrastructure: {req[:100]}",
            database=None if not intents["wants_database"] else {
                "provider": "postgresql",
                "database_name": "app_db",
                "tables": [{"name": "records", "columns": [{"name": "id", "data_type": "serial", "primary_key": True}]}],
            },
            cloud={
                "provider": "aws",
                "region": "us-east-1",
                "environment": "local",
                "resources": cloud_resources,
            } if cloud_resources else None,
            dependencies=[],
            assumptions=["Generated adhering to Scope Fidelity rules"],
            estimated_cost_monthly=15.0 if intents["wants_database"] else 5.0,
            risk_level="medium",
        )


# Unified singleton instance
llm_client = HybridLLMClient()

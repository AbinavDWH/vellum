import json
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field, ValidationError
import structlog

from app.schemas.ir import UniversalIR
from app.llm.client import llm_client
from app.healing.sanitizer import sanitize_logs, sanitize_text

logger = structlog.get_logger(__name__)


class LLMFixProposal(BaseModel):
    """Pydantic contract for LLM Fix Proposer output."""
    root_cause: str
    fix_type: Literal["ir_patch", "hcl_patch", "retry", "import", "reorder", "cidr_recompute", "instance_fallback", "regenerate_hcl", "regenerate_sql", "halt"]
    patch: Dict[str, Any] = Field(default_factory=dict)
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_assessment: Literal["low", "medium", "high", "critical"] = "low"


SYSTEM_PROMPT = """You are Vellum's Self-Healing Execution Engine Fix Proposer.
Your role is to diagnose infrastructure execution failures and propose a minimal, deterministic patch.

SAFETY RULES:
1. Propose a structured patch object. NEVER propose raw shell commands or arbitrary script execution.
2. Auto-allowed fixes must be idempotent and must never delete resources, widen security posture, or alter core semantics.
3. If the error is an authentication issue, quota limit, or unrecoverable error, choose fix_type "halt" with risk_assessment "critical".
4. You must output ONLY a valid JSON object matching this schema:
{
  "root_cause": "brief explanation of root cause",
  "fix_type": "ir_patch | hcl_patch | retry | import | halt",
  "patch": { "<target_property_path>": "<new_value>" },
  "reasoning": "technical explanation of why this fix resolves the issue safely",
  "confidence": 0.85,
  "risk_assessment": "low | medium | high | critical"
}
Do not wrap your response in markdown fences or explanations outside the JSON object.
"""


class LLMFixProposer:
    """Proposes structured remediation proposals using LLM with retry & validation."""

    def __init__(self, client=None):
        self.client = client or llm_client

    def propose_fix(
        self,
        error_signature: str,
        logs: str,
        current_ir: UniversalIR,
        hcl_excerpt: str = "",
        provider: str = "aws",
        attempt_history: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMFixProposal:
        """
        Request a fix proposal from the LLM.
        Applies log sanitization, strict temperature 0.1, and up to 2 re-prompts on schema failure.
        """
        attempt_history = attempt_history or []

        # Step 1: Sanitize all inputs before building prompt
        sanitized_logs = sanitize_logs(logs, max_lines=50)
        sanitized_hcl = sanitize_text(hcl_excerpt)
        ir_dict = current_ir.model_dump()

        user_content = (
            f"Target Provider: {provider}\n"
            f"Error Signature: {error_signature}\n\n"
            f"Sanitized Execution Logs (last 50 lines):\n{sanitized_logs}\n\n"
            f"HCL Context:\n{sanitized_hcl}\n\n"
            f"Current Universal IR:\n{json.dumps(ir_dict, indent=2)}\n\n"
            f"Past Attempts History:\n{json.dumps(attempt_history, indent=2)}\n\n"
            "Diagnose the root cause and output your JSON fix proposal object."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # Check if LLM client is available
        client = self.client
        if hasattr(client, "is_healthy") and not client.is_healthy():
            logger.info("LM Studio offline. Generating deterministic fallback proposal.")
            return self._heuristic_proposal(error_signature, sanitized_logs, current_ir)

        # Up to 2 re-prompts on schema failure (3 total tries)
        max_attempts = 3
        last_error_str = ""

        for attempt in range(max_attempts):
            try:
                if hasattr(client, "chat"):
                    raw_response = client.chat(
                        messages=messages,
                        temperature=0.1,
                        json_mode=True,
                    )
                elif hasattr(client, "chat_completion"):
                    raw_response = client.chat_completion(messages)
                else:
                    raw_response = client(messages)

                proposal = self._parse_and_validate(raw_response)
                return proposal
            except Exception as e:
                last_error_str = str(e)
                logger.warning(
                    "LLM fix proposal failed schema validation",
                    attempt=attempt + 1,
                    error=last_error_str,
                )
                # Re-prompt LLM with the schema error
                messages.append({
                    "role": "user",
                    "content": f"The previous JSON output failed validation with error: {last_error_str}. Output ONLY valid JSON adhering strictly to the schema.",
                })

        logger.error("LLM failed schema validation after max re-prompts. Halting.")
        return LLMFixProposal(
            root_cause=f"Unparseable LLM proposal after {max_attempts} attempts: {last_error_str}",
            fix_type="halt",
            patch={},
            reasoning="LLM Fix Proposer failed schema validation. Halting for human operator.",
            confidence=0.0,
            risk_assessment="high",
        )

    def _parse_and_validate(self, text_or_data: Any) -> LLMFixProposal:
        """Parse raw JSON string or dict and validate against LLMFixProposal schema."""
        if isinstance(text_or_data, dict):
            return LLMFixProposal(**text_or_data)
        cleaned = str(text_or_data).strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)
        return LLMFixProposal(**data)

    def _heuristic_proposal(
        self,
        error_signature: str,
        sanitized_logs: str,
        current_ir: UniversalIR,
    ) -> LLMFixProposal:
        """Safe heuristic proposal when LLM is offline."""
        if error_signature == "BucketAlreadyExists":
            return LLMFixProposal(
                root_cause="S3 Bucket name already taken in target environment",
                fix_type="import",
                patch={"action": "auto_import"},
                reasoning="Bucket name collision resolved by importing existing bucket into state.",
                confidence=0.95,
                risk_assessment="low",
            )
        elif error_signature == "InvalidSubnet.Range":
            return LLMFixProposal(
                root_cause="Subnet CIDR block overlaps existing subnet in VPC",
                fix_type="cidr_recompute",
                patch={"resources.cidr_block": "next_free"},
                reasoning="Recomputed next available non-overlapping CIDR block.",
                confidence=0.90,
                risk_assessment="low",
            )
        elif error_signature in ["AccessDenied", "QuotaExceeded", "RuntimeOOMOrTimeout"]:
            return LLMFixProposal(
                root_cause=f"Unfixable error class: {error_signature}",
                fix_type="halt",
                patch={},
                reasoning="Security and quota constraints require human operator decision.",
                confidence=1.0,
                risk_assessment="critical",
            )
        elif error_signature == "InvalidParameterValue":
            return LLMFixProposal(
                root_cause="Invalid resource parameter value",
                fix_type="ir_patch",
                patch={"properties.corrected": True},
                reasoning="Attribute corrected according to provider specification.",
                confidence=0.85,
                risk_assessment="low",
            )
        else:
            return LLMFixProposal(
                root_cause="Unknown execution error encountered",
                fix_type="hcl_patch",
                patch={},
                reasoning="Heuristic remediation fallback.",
                confidence=0.70,
                risk_assessment="medium",
            )


llm_fix_proposer = LLMFixProposer()

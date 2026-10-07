from typing import Dict, Any, Union, Optional
from app.validation.policy import PolicyEngine, RiskLevel
from app.schemas.ir import UniversalIR


class ApprovalEngine:
    """Human-in-the-loop approval gate and preview formatter."""

    def __init__(self, approval_required_globally: bool = True):
        self.approval_required_globally = approval_required_globally

    def _normalize_ir(self, plan: Union[dict, UniversalIR]) -> UniversalIR:
        if isinstance(plan, dict):
            return UniversalIR(**plan)
        return plan

    def requires_approval(self, plan: Union[dict, UniversalIR]) -> bool:
        """Determines if the given plan requires human intervention before execution."""
        if not self.approval_required_globally:
            return False
        
        ir = self._normalize_ir(plan)
        risk, _, _ = PolicyEngine.evaluate_risk(ir)
        # Read-only or inspection operations can auto-execute if configured
        if risk == RiskLevel.LOW and ir.intent == "inspect_schema":
            return False
        return True

    def classify_risk(self, plan: Union[dict, UniversalIR]) -> RiskLevel:
        """Classify risk level (LOW, MEDIUM, HIGH, CRITICAL)."""
        ir = self._normalize_ir(plan)
        risk, _, _ = PolicyEngine.evaluate_risk(ir)
        return risk

    def get_confirmation_requirements(self, plan: Union[dict, UniversalIR]) -> tuple[bool, Optional[str]]:
        """Return (requires_confirmation_text, confirmation_phrase)"""
        ir = self._normalize_ir(plan)
        _, req_text, phrase = PolicyEngine.evaluate_risk(ir)
        return req_text, phrase

    def format_plan_preview(self, plan: Union[dict, UniversalIR]) -> str:
        """Generate human-readable preview summary for the approval gate."""
        ir = self._normalize_ir(plan)
        risk = self.classify_risk(ir)

        risk_emoji = {
            RiskLevel.LOW: "🟢 LOW",
            RiskLevel.MEDIUM: "🟡 MEDIUM",
            RiskLevel.HIGH: "🟠 HIGH",
            RiskLevel.CRITICAL: "🔴 CRITICAL",
        }.get(risk, "🟡 MEDIUM")

        lines = [
            f"==================================================",
            f"          VELLUM INFRASTRUCTURE PLAN PREVIEW       ",
            f"==================================================",
            f"Intent:     {ir.intent}",
            f"Risk Level: {risk_emoji}",
            f"Summary:    {ir.description or 'Custom Infrastructure & Database deployment'}",
            f"Est. Cost:  ~${ir.estimated_cost_monthly or 0.0:.2f}/month",
            "",
            "PLANNED ACTIONS:",
        ]

        if ir.database:
            lines.append(f"• Database Engine: {ir.database.provider.upper()} ({ir.database.database_name})")
            for t in ir.database.tables:
                col_names = ", ".join(c.name for c in t.columns[:4])
                if len(t.columns) > 4:
                    col_names += f" (+{len(t.columns)-4} more)"
                lines.append(f"  - CREATE TABLE {t.name} ({col_names})")
            for col in ir.database.collections:
                embedded = f" [Embedded: {', '.join(col.embedded_documents)}]" if col.embedded_documents else ""
                lines.append(f"  - CREATE COLLECTION {col.name}{embedded}")
            if ir.database.extensions:
                lines.append(f"  - Extensions: {', '.join(ir.database.extensions)}")


        if ir.cloud:
            lines.append(f"• Cloud Provider: {ir.cloud.provider.upper()} ({ir.cloud.region})")
            requested_res = [r for r in ir.cloud.resources if not getattr(r, "is_dependency", False)]
            dep_res = [r for r in ir.cloud.resources if getattr(r, "is_dependency", False)]

            if requested_res:
                lines.append("  You asked for:")
                for r in requested_res:
                    lines.append(f"    - CREATE {r.type.upper()}: {r.name}")
                    is_web = bool(
                        getattr(r, "properties", {}).get("website") is True
                        or getattr(r, "properties", {}).get("static_site") is True
                        or r.type in ["static_site", "website_hosting"]
                        or "website" in r.name.lower()
                    )
                    if is_web:
                        lines.append(f"      ⚠️ Warning Chip: This bucket will be publicly readable")

            if dep_res:
                lines.append("  Required because: (Dependencies):")
                for r in dep_res:
                    reason = getattr(r, "dependency_reason", None) or "Technical dependency"
                    lines.append(f"    - CREATE {r.type.upper()}: {r.name} ({reason})")

        lines.extend([
            "",
            "APPROVAL REQUIRED:",
            "  [✅ APPROVE]  [✏️ EDIT]  [❌ REJECT]",
            "==================================================",
        ])

        return "\n".join(lines)


approval_engine = ApprovalEngine()

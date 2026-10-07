import json
import re
from typing import Any, Dict, Optional, Tuple
from app.schemas.ir import UniversalIR, ClarificationResponse


class LLMParser:
    """Robust parser for LLM responses."""

    @staticmethod
    def extract_json(raw_text: str) -> Dict[str, Any]:
        """Extract a JSON object from text that may contain markdown or extraneous text."""
        raw_text = raw_text.strip()
        
        # 1. Direct parse attempt
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # 2. Extract from markdown code fences ```json ... ```
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(fence_pattern, raw_text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

        # 3. Find outermost curly braces
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            substring = raw_text[start : end + 1]
            try:
                return json.loads(substring)
            except json.JSONDecodeError:
                pass

        # 4. Search for valid JSON dict amongst candidate curly brace segments (handles reasoning notes with braces)
        brace_indices = [i for i, ch in enumerate(raw_text) if ch == "{"]
        # Prioritize later '{' since models usually output reasoning first and final JSON last
        for start_idx in reversed(brace_indices):
            end_idx = raw_text.rfind("}")
            while end_idx > start_idx:
                candidate = raw_text[start_idx : end_idx + 1]
                try:
                    loaded = json.loads(candidate)
                    if isinstance(loaded, dict) and len(loaded) > 0:
                        return loaded
                except Exception:
                    pass
                end_idx = raw_text.rfind("}", 0, end_idx)

        raise ValueError(f"Could not parse valid JSON from LLM response:\n{raw_text[:300]}...")

    @classmethod
    def parse_universal_ir(cls, raw_text: str) -> UniversalIR:
        """Parse raw LLM output into a validated UniversalIR instance."""
        data = cls.extract_json(raw_text)

        # Unwrap top-level envelope if model wrapped it in {"plan": ...} or {"universal_ir": ...}
        for wrapper_key in ["plan", "universal_ir", "infrastructure_plan", "result", "data"]:
            if isinstance(data, dict) and wrapper_key in data and isinstance(data[wrapper_key], dict):
                inner = data[wrapper_key]
                if any(k in inner for k in ["cloud", "database", "intent", "resources"]):
                    data = inner
                    break

        return UniversalIR(**data)

    @classmethod
    def parse_clarification(cls, raw_text: str) -> ClarificationResponse:
        """Parse clarification check output."""
        cleaned = raw_text.strip()
        if "READY" in cleaned.upper() and ("{" not in cleaned or cleaned.upper().startswith("READY")):
            return ClarificationResponse(is_ready=True, questions=[])

        try:
            data = cls.extract_json(cleaned)
            return ClarificationResponse(**data)
        except Exception:
            # If parsing fails but contains text, treat as ready if minimal or ask general question
            return ClarificationResponse(is_ready=True, questions=[], raw_message=cleaned)

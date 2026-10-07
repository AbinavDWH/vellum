import json
import re
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import structlog

from app.database import SessionLocal
from app.models import ChatMessageRecord, PlanRecord

logger = structlog.get_logger(__name__)


class RAGEngine:
    """
    Retrieval-Augmented Generation (RAG) & Chat History Engine.
    Stores conversations, retrieves contextual history, and augments LLM prompts
    with historical architectural decisions, past plans, and conversation memory.
    """

    def save_message(
        self,
        sender: str,
        text: str,
        session_id: str = "default",
        plan_id: Optional[str] = None,
        clarification: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> ChatMessageRecord:
        """Store a chat message in the database."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            record = ChatMessageRecord(
                session_id=session_id,
                sender=sender,
                text=text,
                plan_id=plan_id,
                clarification_json=json.dumps(clarification) if clarification else None,
                metadata_json=json.dumps(metadata or {}),
                created_at=datetime.datetime.utcnow(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record
        except Exception as e:
            logger.error("Failed to save chat message", error=str(e))
            db.rollback()
            raise
        finally:
            if close_db:
                db.close()

    def get_history(
        self,
        session_id: str = "default",
        limit: int = 100,
        db: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve conversation history for a session."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            records = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session_id)
                .order_by(ChatMessageRecord.created_at.asc())
                .limit(limit)
                .all()
            )

            result = []
            for r in records:
                clarification = None
                if r.clarification_json:
                    try:
                        clarification = json.loads(r.clarification_json)
                    except Exception:
                        pass

                result.append({
                    "id": str(r.id),
                    "sender": r.sender,
                    "text": r.text,
                    "plan_id": r.plan_id,
                    "timestamp": r.created_at.isoformat() if r.created_at else "",
                    "clarification": clarification,
                })
            return result
        finally:
            if close_db:
                db.close()

    def clear_history(
        self,
        session_id: str = "default",
        db: Optional[Session] = None,
    ) -> bool:
        """Clear chat history for a session."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            db.query(ChatMessageRecord).filter(ChatMessageRecord.session_id == session_id).delete()
            db.commit()
            return True
        except Exception as e:
            logger.error("Failed to clear chat history", error=str(e))
            db.rollback()
            return False
        finally:
            if close_db:
                db.close()

    def retrieve_context(
        self,
        query: str,
        session_id: str = "default",
        max_history_turns: int = 6,
        max_plans: int = 3,
        db: Optional[Session] = None,
    ) -> str:
        """
        RAG retrieval: extracts relevant context from:
        1. Recent conversation dialogue
        2. Relevant past infrastructure & database plans
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        context_sections = []

        try:
            # 1. Retrieve Recent Dialogue History
            recent_msgs = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session_id)
                .order_by(ChatMessageRecord.created_at.desc())
                .limit(max_history_turns)
                .all()
            )
            recent_msgs.reverse()

            if recent_msgs:
                dialogue_lines = []
                for m in recent_msgs:
                    role_tag = "User" if m.sender == "user" else "Assistant"
                    snippet = m.text[:200] + ("..." if len(m.text) > 200 else "")
                    dialogue_lines.append(f"- {role_tag}: {snippet}")
                context_sections.append("Recent Chat History:\n" + "\n".join(dialogue_lines))

            # 2. Retrieve Past Architectural Plans (Semantic / Keyword Matching)
            query_tokens = set(re.findall(r"\w+", query.lower()))
            # Remove basic stop words
            stop_words = {"i", "need", "a", "an", "the", "for", "with", "and", "or", "to", "in", "on", "of", "my", "please", "can", "you", "make", "create", "add"}
            keywords = query_tokens - stop_words

            past_plans = (
                db.query(PlanRecord)
                .order_by(PlanRecord.created_at.desc())
                .limit(10)
                .all()
            )

            scored_plans = []
            for p in past_plans:
                score = 0
                prompt_text = (p.prompt or "").lower()
                intent_text = (p.intent or "").lower()
                combined = f"{prompt_text} {intent_text}"
                
                # Check keyword overlap
                for kw in keywords:
                    if len(kw) > 2 and kw in combined:
                        score += 2

                # If query refers to "database", "table", "s3", "bucket", "vpc", check IR
                if p.ir_json:
                    try:
                        ir_data = json.loads(p.ir_json)
                        if "database" in ir_data and ir_data["database"]:
                            db_name = ir_data["database"].get("database_name", "")
                            if db_name and db_name.lower() in query.lower():
                                score += 5
                            for tbl in ir_data["database"].get("tables", []):
                                t_name = tbl.get("name", "")
                                if t_name and t_name.lower() in query.lower():
                                    score += 4
                        if "cloud" in ir_data and ir_data["cloud"]:
                            for res in ir_data["cloud"].get("resources", []):
                                r_name = res.get("name", "")
                                if r_name and r_name.lower() in query.lower():
                                    score += 4
                    except Exception:
                        pass

                scored_plans.append((score, p))

            # Sort by relevance score
            scored_plans.sort(key=lambda x: x[0], reverse=True)
            relevant_plans = [p for score, p in scored_plans if score > 0][:max_plans]

            # If no direct match but plans exist, take the most recent plan as immediate context
            if not relevant_plans and past_plans:
                relevant_plans = [past_plans[0]]

            if relevant_plans:
                plan_lines = []
                for p in relevant_plans:
                    summary = f"- Plan [{p.plan_id}] (Status: {p.status}, Risk: {p.risk_level})\n"
                    summary += f"  Prompt: {p.prompt[:150]}\n"
                    if p.ir_json:
                        try:
                            ir_data = json.loads(p.ir_json)
                            if "database" in ir_data and ir_data["database"]:
                                db_info = ir_data["database"]
                                table_names = [t.get("name") for t in db_info.get("tables", [])]
                                summary += f"  Existing Database: {db_info.get('provider')} '{db_info.get('database_name')}' with tables: {', '.join(table_names)}\n"
                            if "cloud" in ir_data and ir_data["cloud"]:
                                cloud_info = ir_data["cloud"]
                                res_types = [f"{r.get('type')}:{r.get('name')}" for r in cloud_info.get("resources", [])]
                                summary += f"  Existing Cloud Resources: {', '.join(res_types)}\n"
                        except Exception:
                            pass
                    plan_lines.append(summary)

                context_sections.append("Relevant Existing Infrastructure & Database Architecture:\n" + "\n".join(plan_lines))

            if not context_sections:
                return ""

            return "\n\n".join(context_sections)

        except Exception as e:
            logger.error("RAG context retrieval failed", error=str(e))
            return ""
        finally:
            if close_db:
                db.close()


rag_engine = RAGEngine()

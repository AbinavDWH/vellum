"""requirements.md must stay a short, factual data file: only what the user stated."""
import re
from app.config import settings
from app.llm.client import llm_client
from app.requirements.manager import requirements_manager

# Things the old verbose spec added on its own. None may appear unless the user asked.
EXTRAS = ["KMS", "NAT", "Multi-AZ", "multi_az", "Secrets Manager", "CloudWatch", "Flow Logs",
          "RPO", "RTO", "Glacier", "sg-alb", "password_hash", "encryption", "versioning"]


def fb(current, prompt, env="local"):
    return llm_client._fallback_synthesize_requirements(current, prompt, "aws", env)


def test_default_template_is_tiny_and_has_no_hints():
    md = requirements_manager.get_default_template("aws", "local")
    assert len(md) < 300
    assert "TBD" not in md
    assert not any(x in md for x in EXTRAS)
    assert "**Cloud Provider**: AWS" in md and "**Environment**: local" in md


def test_header_lines_still_sync_to_prod():
    md = requirements_manager.get_default_template("aws", "local")
    out = requirements_manager.sync_metadata(md, cloud_provider="aws", environment="prod")
    assert "**Environment**: prod" in out


def test_s3_only_request_has_no_extras():
    md = fb("", "create an s3 bucket named my-logs-123")
    assert "- s3_bucket: name=my-logs-123" in md
    assert "vpc" not in md and "database" not in md and "compute" not in md
    assert "## Notes" not in md          # plain request: the resource line already says it
    assert not any(x in md for x in EXTRAS)
    assert len(md) < 250


def test_database_has_no_invented_schema_or_ha():
    md = fb("", "create a postgres database with table orders")
    assert "- database: engine=postgresql" in md
    assert "- orders" in md
    assert "uuid" not in md.lower() and "password_hash" not in md
    assert "multi_az" not in md


def test_user_stated_extras_are_recorded():
    md = fb("", "create a mysql database multi-az on db.t3.small")
    assert "multi_az=true" in md and "instance_class=db.t3.small" in md and "engine=mysql" in md


def test_merge_keeps_old_facts_and_updates_changed_values():
    md = fb("", "create an s3 bucket named a-bucket-1")
    md = fb(md, "also add a vpc 10.1.0.0/16")
    md = fb(md, "turn on versioning for the bucket")
    assert "name=a-bucket-1" in md and "versioning=true" in md
    assert "- vpc: cidr=10.1.0.0/16" in md
    assert md.count("## Resources") == 1 and md.count("- s3_bucket") == 1


def test_notes_do_not_grow_forever():
    md = ""
    for i in range(10):
        md = fb(md, f"keep the bucket private, allow only port {8000 + i}")
    assert md.count("keep the bucket private") <= 3
    assert len(md) < 800


def test_constraint_is_kept_as_a_note():
    md = fb("", "create an s3 bucket named my-logs-123, keep it private")
    assert "## Notes" in md and "keep it private" in md


def test_environment_written_exactly_as_given():
    assert "**Environment**: staging" in fb("", "create an s3 bucket", env="staging")


def test_llm_result_for_s3_only_spec_is_accepted(monkeypatch):
    """Old check demanded 'Database' and 'Network' words, so an S3-only spec was thrown away."""
    good = "# Spec\n- **Cloud Provider**: AWS\n- **Environment**: local\n\n## Resources\n- s3_bucket: name=x-bucket\n"
    monkeypatch.setattr(llm_client, "is_healthy", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: good)
    out = llm_client.synthesize_requirements("", "create bucket x-bucket", "ok", "aws", "local")
    assert out.strip() == good.strip()


def test_llm_result_without_header_uses_fallback(monkeypatch):
    monkeypatch.setattr(llm_client, "is_healthy", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: "random prose with no header")
    out = llm_client.synthesize_requirements("", "create an s3 bucket named my-b-1", "ok", "aws", "local")
    assert "**Cloud Provider**" in out and "s3_bucket" in out


def test_prompt_forbids_extras():
    from app.llm.prompts import REQUIREMENTS_SYNTHESIS_SYSTEM_PROMPT as P
    assert len(P) < 2500
    assert "NEVER add defaults" in P and "suggestions" in P
    assert "TBD" not in P.replace('no "TBD"', "").replace('or "TBD"', "")


def test_goal_kept_when_nothing_structured_can_be_extracted():
    md = fb("", "I want a backend for a medical telemedicine platform")
    assert "## Notes" in md and "telemedicine" in md

import pytest
from app.healing.sanitizer import sanitize_logs, sanitize_for_prompt
from app.healing.proposer import LLMFixProposer
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan
from unittest.mock import MagicMock

def test_sanitizer_redacts_aws_credentials():
    raw_logs = (
        "2026-10-05T12:00:00Z [INFO] Initializing AWS provider\n"
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
        "Error: InvalidParameterValue"
    )
    sanitized = sanitize_logs(raw_logs)
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in sanitized
    assert "[REDACTED_AWS_KEY_ID]" in sanitized
    assert "[REDACTED_SECRET]" in sanitized

def test_sanitizer_redacts_database_uris():
    raw_logs = (
        "Connecting to postgres://admin:SuperSecretP@ssw0rd!@db.internal.net:5432/prod_db ...\n"
        "Connecting to mysql://root:toor12345@10.0.0.5:3306/ecommerce ...\n"
        "Connecting to mongodb://user:pass987@cluster0.mongodb.net/app ...\n"
        "Connection refused"
    )
    sanitized = sanitize_logs(raw_logs)
    assert "SuperSecretP@ssw0rd!" not in sanitized
    assert "toor12345" not in sanitized
    assert "pass987" not in sanitized
    assert "[REDACTED_CREDS]" in sanitized or "[REDACTED_PASSWORD]" in sanitized

def test_sanitizer_redacts_bearer_tokens_and_jwt():
    raw_logs = (
        "HTTP Request: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n"
        "Authorization: Bearer secret_api_token_xyz12345abc\n"
        "Error: 401 Unauthorized"
    )
    sanitized = sanitize_logs(raw_logs)
    assert "eyJhbGciOi" not in sanitized
    assert "secret_api_token_xyz12345abc" not in sanitized
    assert "[REDACTED_TOKEN]" in sanitized

def test_sanitizer_redacts_private_keys():
    raw_logs = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y123456789abcdefghijklmnopqrstuvwxyz...\n"
        "-----END RSA PRIVATE KEY-----\n"
        "Failed to load SSH identity"
    )
    sanitized = sanitize_logs(raw_logs)
    assert "MIIEowIBAAKCAQEA" not in sanitized
    assert "[REDACTED_PRIVATE_KEY]" in sanitized

def test_sanitizer_caps_to_max_lines():
    raw_logs = "\n".join([f"Line {i}: test log output" for i in range(100)])
    sanitized = sanitize_logs(raw_logs, max_lines=50)
    lines = sanitized.strip().split("\n")
    assert len(lines) == 50
    assert "Line 50" in lines[0]
    assert "Line 99" in lines[-1]

def test_planted_fake_secret_never_reaches_llm_prompt():
    """Verify that planted fake secrets in logs never reach LLM prompt via mock client capture."""
    planted_logs = (
        "Execution step failed.\n"
        "AWS_ACCESS_KEY_ID=AKIA1111222233334444\n"
        "AWS_SECRET_ACCESS_KEY=TopSecretKeyWithLettersAndNumbers12345\n"
        "DB_URL=postgres://vellum:super_classified_pw@localhost:5432/vellum\n"
        "Error: BucketAlreadyExists: The requested bucket name is not available"
    )

    mock_llm_proposal = {
        "root_cause": "Bucket name collision",
        "fix_type": "import",
        "patch": {},
        "reasoning": "Import bucket or rename",
        "confidence": 0.95,
        "risk_assessment": "low"
    }

    mock_client = MagicMock()
    mock_client.is_healthy.return_value = True
    mock_client.chat.return_value = mock_llm_proposal

    proposer = LLMFixProposer(client=mock_client)
    proposal = proposer.propose_fix(
        error_signature="BucketAlreadyExists",
        logs=planted_logs,
        current_ir=UniversalIR(intent="deploy_cloud", cloud=CloudPlan()),
        hcl_excerpt="resource \"aws_s3_bucket\" \"test\" {}",
        provider="aws",
        attempt_history=[]
    )

    assert proposal.fix_type == "import"
    assert mock_client.chat.called

    # Inspect the prompt passed to the mock LLM client
    call_kwargs = mock_client.chat.call_args[1]
    called_messages = call_kwargs.get("messages", [])
    prompt_content = " ".join([m["content"] for m in called_messages])

    # Assert planted secrets were redacted and never appeared in prompt
    assert "AKIA1111222233334444" not in prompt_content
    assert "TopSecretKeyWithLettersAndNumbers12345" not in prompt_content
    assert "super_classified_pw" not in prompt_content
    assert "[REDACTED_AWS_KEY_ID]" in prompt_content
    assert "[REDACTED_CREDS]" in prompt_content or "[REDACTED_PASSWORD]" in prompt_content


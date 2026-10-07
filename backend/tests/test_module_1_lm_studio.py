import pytest
import json
from app.llm.client import llm_client


def test_lm_studio_connection():
    if not llm_client.is_healthy():
        pytest.skip("LM Studio is not reachable on localhost:1234")
    response = llm_client.chat([
        {"role": "user", "content": "Respond with exactly: HELLO_VELLUM"}
    ])
    assert "HELLO_VELLUM" in response.upper()


def test_lm_studio_json_mode():
    if not llm_client.is_healthy():
        pytest.skip("LM Studio is not reachable on localhost:1234")
    response = llm_client.chat([
        {"role": "user", "content": 'Return JSON: {"status": "ok"}'}
    ], json_mode=True)
    from app.llm.parser import LLMParser
    data = LLMParser.extract_json(response)
    assert data.get("status") == "ok"

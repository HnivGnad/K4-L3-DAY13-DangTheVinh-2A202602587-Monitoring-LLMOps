from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                headers={"x-request-id": "req-cp1test1"},
                json={
                    "user_id": "student-01@example.com",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability; call 090 123 4567",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-cp1test1"
    assert response.headers["x-response-time-ms"].isdigit()
    assert response.json()["correlation_id"] == "req-cp1test1"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_event = next(event for event in events if event["event"] == "request_received")
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert request_event["correlation_id"] == "req-cp1test1"
    assert request_event["user_id_hash"]
    assert request_event["user_id_hash"] != "student-01@example.com"
    assert request_event["session_id"] == "session-01"
    assert request_event["feature"] == "qa"
    assert request_event["model"] == "claude-sonnet-4-5"
    assert request_event["env"] == "dev"
    assert "090 123 4567" not in json.dumps(events, ensure_ascii=False)
    assert "REDACTED_PHONE_VN" in request_event["payload"]["message_preview"]
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True

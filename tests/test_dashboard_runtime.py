from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_dashboard import generate_dashboard


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dashboard_contains_exactly_six_panels(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    records = [
        {
            "ts": "2026-09-30T03:00:00Z",
            "event": "request_received",
            "correlation_id": "req-12345678",
        },
        {
            "ts": "2026-09-30T03:00:01Z",
            "event": "response_sent",
            "correlation_id": "req-12345678",
            "latency_ms": 150,
            "ttft_ms": 50,
            "tokens_in": 20,
            "tokens_out": 80,
            "cost_usd": 0.00126,
            "quality_score": 0.9,
            "tool_success": True,
        },
    ]
    log_path.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(
        log_path, REPO_ROOT / "config" / "dashboard.yaml", output_path
    )

    dashboard = output_path.read_text(encoding="utf-8")
    assert dashboard.count('<article class="panel"') == 6
    for panel_id in ("latency", "traffic", "errors", "cost", "tokens", "quality"):
        assert f'id="{panel_id}"' in dashboard
    assert "P95 latency" in dashboard
    assert "Retrieval success" in dashboard
    assert "Source: data/logs.jsonl" in dashboard

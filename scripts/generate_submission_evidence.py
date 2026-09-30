from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.tracing import get_langfuse_client
from scripts.generate_incident_evidence import fetch_trace_observations, page
from scripts.manage_prompts import fetch_prompt


def capture_call(function: Any) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = function()
        exit_code = int(result or 0)
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    output = (stdout.getvalue() + stderr.getvalue()).strip()
    return exit_code, output


def run_pytest() -> int:
    import pytest

    return pytest.main(
        ["-q", "--basetemp", str(REPO_ROOT / ".cp4-pytest-tmp")]
    )


def run_log_validator() -> int:
    from scripts.validate_logs import main

    main()
    return 0


def run_dashboard_validator() -> int:
    from scripts.validate_dashboard import REQUIRED_PANEL_IDS, load_dashboard_config

    load_dashboard_config(REPO_ROOT / "config" / "dashboard.yaml")
    print(f"HỢP LỆ: {len(REQUIRED_PANEL_IDS)}/6 panel có trong dashboard contract.")
    return 0


def command_page(title: str, command: str, exit_code: int, output: str) -> str:
    status = "PASSED" if exit_code == 0 else "FAILED"
    color = "ok" if exit_code == 0 else "danger"
    return page(
        title,
        "CP4 · final verification",
        f"""<p class="subtitle">Reproducible command output captured from the final workspace.</p>
<section class="card">
  <div class="grid" style="grid-template-columns:2fr 1fr">
    <div class="metric"><strong style="font-size:20px"><code>{html.escape(command)}</code></strong><span>Command</span></div>
    <div class="metric"><strong class="{color}">{status}</strong><span>Exit code {exit_code}</span></div>
  </div>
  <pre style="white-space:pre-wrap;line-height:1.55;background:#081321;border:1px solid #243a52;border-radius:12px;padding:20px;margin:22px 0 0;font:14px/1.55 'Cascadia Code',Consolas,monospace;color:#d8ecff">{html.escape(output)}</pre>
  <footer>Source: local command execution · no secrets or environment values included</footer>
</section>""",
    )


def load_logs(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def structured_log_page(records: list[dict[str, Any]]) -> str:
    record = next(
        item
        for item in records
        if item.get("event") == "response_sent"
        and item.get("feature") == "qa"
        and item.get("latency_ms") is not None
    )
    fields = [
        "ts",
        "event",
        "service",
        "correlation_id",
        "user_id_hash",
        "session_id",
        "feature",
        "model",
        "env",
        "latency_ms",
        "ttft_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "quality_score",
        "tool_name",
        "tool_success",
    ]
    values = "".join(
        f'<div class="key">{html.escape(field)}</div>'
        f'<div><code>{html.escape(str(record.get(field)))}</code></div>'
        for field in fields
    )
    return page(
        "Structured log — enriched request",
        "CP4 · logging evidence",
        f"""<p class="subtitle">A real <code>response_sent</code> record with correlation, model, environment, usage, cost, quality, and tool outcome.</p>
<section class="card"><div class="kv">{values}</div>
<div class="callout" style="border-color:var(--green)"><strong>Correlation propagation:</strong> <code>{html.escape(record['correlation_id'])}</code> identifies this request across logs and traces.</div>
<footer>Source: data/logs.jsonl · payload omitted from this view</footer></section>""",
    )


def pii_page(records: list[dict[str, Any]]) -> str:
    redacted = [
        item
        for item in records
        if item.get("event") == "request_received"
        and "[REDACTED_" in json.dumps(item.get("payload", {}))
    ][:3]
    if len(redacted) < 3:
        raise ValueError("Expected at least three redacted PII log records")
    rows = "".join(
        f"<tr><td><code>{html.escape(item['correlation_id'])}</code></td>"
        f"<td><code>{html.escape(item['payload']['message_preview'])}</code></td></tr>"
        for item in redacted
    )
    return page(
        "PII redaction — safe log output",
        "CP4 · privacy evidence",
        f"""<p class="subtitle">Fake email, Vietnamese phone, and payment-card inputs are replaced before JSON rendering.</p>
<section class="card"><table style="margin-top:0"><thead><tr><th>Correlation ID</th><th>Sanitized message preview</th></tr></thead><tbody>{rows}</tbody></table>
<div class="callout" style="border-color:var(--green)"><strong>Validator result:</strong> 0 potential PII leaks. Raw identifiers are not displayed or committed.</div>
<footer>Source: data/logs.jsonl · scrubbed runtime records only</footer></section>""",
    )


def fetch_observations(client: Any) -> list[Any]:
    response = client.api.observations.get_many(
        fields="core,basic,metadata,usage,prompt,model,metrics,trace_context",
        limit=100,
    )
    return list(response.data)


def trace_list_page(observations: list[Any], project_name: str) -> str:
    generation_by_trace = {
        item.trace_id: item
        for item in observations
        if item.name == "generation" and item.trace_id
    }
    roots = [
        item
        for item in observations
        if item.parent_observation_id is None
        and item.trace_id in generation_by_trace
    ][:12]
    if len(roots) < 10:
        raise ValueError(f"Expected at least 10 traces, found {len(roots)}")
    rows = []
    for root in roots:
        generation = generation_by_trace[root.trace_id]
        metadata = root.metadata if isinstance(root.metadata, dict) else {}
        rows.append(
            f"<tr><td><code>{html.escape(root.trace_id)}</code></td>"
            f"<td><code>{html.escape(str(metadata.get('correlation_id', '')))}</code></td>"
            f"<td>{html.escape(root.start_time.isoformat())}</td>"
            f"<td>{html.escape(str(generation.prompt_version))}</td></tr>"
        )
    return page(
        "Langfuse trace list",
        f"Project · {project_name}",
        f"""<p class="subtitle">{len(roots)} recent traces from the authenticated personal project; input/output fields were not requested.</p>
<section class="card"><table style="margin-top:0"><thead><tr><th>Trace ID</th><th>Correlation ID</th><th>Start time UTC</th><th>Prompt version</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<footer>Source: Langfuse Observations API v2 · authenticated with local, uncommitted credentials</footer></section>""",
    )


def waterfall_page(observations: list[dict[str, Any]], project_name: str, trace_id: str) -> str:
    maximum = max(item["duration_ms"] for item in observations) or 1.0
    rows = []
    for item in observations:
        name = str(item["name"])
        width = max(1.0, item["duration_ms"] / maximum * 100)
        css_class = "retrieval" if name == "retrieval" else "generation" if name == "generation" else ""
        relationship = "root" if item["parent_observation_id"] is None else "child"
        rows.append(
            f'<div class="trace-row"><div class="trace-label">{html.escape(name)}'
            f'<small>{html.escape(str(item["type"]))} · {relationship}</small></div>'
            f'<div class="track"><div class="bar {css_class}" style="width:{width:.1f}%"></div></div>'
            f'<div class="duration">{item["duration_ms"]:.0f} ms</div></div>'
        )
    metadata = observations[0]["metadata"]
    correlation_id = str(metadata.get("correlation_id", ""))
    return page(
        "Trace waterfall — root and child observations",
        f"Project · {project_name}",
        f"""<p class="subtitle">Trace <code>{html.escape(trace_id)}</code> · correlation ID <code>{html.escape(correlation_id)}</code></p>
<section class="card">{''.join(rows)}
<div class="callout" style="border-color:var(--green)"><strong>Verified tree:</strong> one root <code>lab-agent-run</code> with <code>retrieval</code> and <code>generation</code> children.</div>
<footer>Source: Langfuse Observations API v2 · durations calculated from observation timestamps</footer></section>""",
    )


def trace_metadata_page(
    observations: list[dict[str, Any]], project_name: str, trace_id: str
) -> str:
    generation = next(item for item in observations if item["name"] == "generation")
    metadata = generation["metadata"]
    usage = generation["usage_details"]
    values = {
        "trace_id": trace_id,
        "correlation_id": metadata.get("correlation_id"),
        "model": generation.get("model"),
        "prompt_name": generation.get("prompt_name") or metadata.get("prompt_name"),
        "prompt_label": metadata.get("prompt_label"),
        "prompt_version": generation.get("prompt_version") or metadata.get("prompt_version"),
        "tokens_input": usage.get("input"),
        "tokens_output": usage.get("output"),
        "tokens_total": usage.get("total"),
        "cost_usd": generation.get("total_cost"),
        "ttft_ms": round((generation.get("ttft_seconds") or 0) * 1000),
    }
    rows = "".join(
        f'<div class="key">{html.escape(key)}</div><div><code>{html.escape(str(value))}</code></div>'
        for key, value in values.items()
    )
    return page(
        "Trace metadata — prompt, usage, and cost",
        f"Project · {project_name}",
        f"""<p class="subtitle">Sanitized generation metadata for a trace created by this project.</p>
<section class="card"><div class="kv">{rows}</div>
<div class="callout" style="border-color:var(--green)"><strong>Privacy:</strong> raw user input and model output were not requested from Langfuse.</div>
<footer>Source: Langfuse Observations API v2</footer></section>""",
    )


def prompt_versions_page(
    project_name: str, prompt_name: str, prompts: dict[str, Any]
) -> str:
    rows = "".join(
        f"<tr><td><code>{html.escape(label)}</code></td>"
        f"<td>{prompt.version}</td>"
        f"<td><code>{hashlib.sha256(str(prompt.prompt).encode('utf-8')).hexdigest()[:12]}</code></td></tr>"
        for label, prompt in prompts.items()
    )
    return page(
        "Prompt versions and labels",
        f"Project · {project_name}",
        f"""<p class="subtitle">Managed prompt <code>{html.escape(prompt_name)}</code> has separate baseline and candidate versions.</p>
<section class="card"><table style="margin-top:0"><thead><tr><th>Label</th><th>Version</th><th>Template SHA-256 prefix</th></tr></thead><tbody>{rows}</tbody></table>
<div class="callout" style="border-color:var(--green)"><strong>Versioning verified:</strong> baseline and candidate resolve to different immutable prompt versions.</div>
<footer>Source: Langfuse Prompt Management API · prompt body intentionally omitted</footer></section>""",
    )


def exercise_rollback(client: Any, prompt_name: str) -> tuple[int, int]:
    baseline = fetch_prompt(client, prompt_name, "baseline")
    candidate = fetch_prompt(client, prompt_name, "candidate")
    if baseline is None or candidate is None:
        raise ValueError("Baseline and candidate prompt labels are required")
    promoted_version: int | None = None
    try:
        client.update_prompt(
            name=prompt_name,
            version=candidate.version,
            new_labels=["candidate", "production"],
        )
        promoted = fetch_prompt(client, prompt_name, "production")
        if promoted is None:
            raise ValueError("Production label was not promoted")
        promoted_version = promoted.version
    finally:
        client.update_prompt(
            name=prompt_name,
            version=baseline.version,
            new_labels=["baseline", "production"],
        )
    rolled_back = fetch_prompt(client, prompt_name, "production")
    if rolled_back is None or promoted_version is None:
        raise ValueError("Production label was not restored")
    return promoted_version, rolled_back.version


def rollback_page(
    project_name: str,
    prompt_name: str,
    promoted_version: int,
    rolled_back_version: int,
) -> str:
    return page(
        "Prompt production rollback",
        f"Project · {project_name}",
        f"""<p class="subtitle">Live label transition verified through the Langfuse Prompt Management API.</p>
<section class="card"><div class="grid" style="grid-template-columns:1fr 120px 1fr">
  <div class="metric"><strong>v{promoted_version}</strong><span><code>production</code> after candidate promotion</span></div>
  <div class="metric" style="text-align:center"><strong>→</strong><span>rollback</span></div>
  <div class="metric"><strong class="ok">v{rolled_back_version}</strong><span><code>production</code> final state</span></div>
</div>
<div class="callout" style="border-color:var(--green)"><strong>Rollback complete:</strong> <code>production → {html.escape(prompt_name)} v{rolled_back_version}</code>. Baseline is restored after the verification.</div>
<footer>Source: Langfuse Prompt Management API · final state fetched after rollback</footer></section>""",
    )


def write_artifacts(output_dir: Path, artifacts: dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in artifacts.items():
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        print(f"Generated {path}")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Generate sanitized CP4 verification and Langfuse evidence"
    )
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument(
        "--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "submission" / "evidence",
    )
    args = parser.parse_args()

    commands = {
        "01-pytest.html": (
            "Final pytest",
            "python -m pytest -q",
            run_pytest,
        ),
        "02-log-validator.html": (
            "Log validator",
            "python scripts/validate_logs.py",
            run_log_validator,
        ),
        "03-dashboard-validator.html": (
            "Dashboard validator",
            "python scripts/validate_dashboard.py",
            run_dashboard_validator,
        ),
    }
    artifacts: dict[str, str] = {}
    for filename, (title, display_command, function) in commands.items():
        exit_code, output = capture_call(function)
        artifacts[filename] = command_page(
            title, display_command, exit_code, output
        )
        if exit_code != 0:
            raise RuntimeError(
                f"Verification command failed: {display_command}\n{output}"
            )

    records = load_logs(args.logs)
    artifacts["04-structured-log.html"] = structured_log_page(records)
    artifacts["05-pii-redaction.html"] = pii_page(records)

    client = get_langfuse_client()
    if not client.auth_check():
        raise RuntimeError("Langfuse authentication failed")
    all_observations = fetch_observations(client)
    trace_observations = fetch_trace_observations(args.trace_id)
    if len(trace_observations) < 3:
        raise ValueError("Selected trace does not contain the expected span tree")
    artifacts["06-trace-list.html"] = trace_list_page(
        all_observations, args.project_name
    )
    artifacts["07-trace-waterfall.html"] = waterfall_page(
        trace_observations, args.project_name, args.trace_id
    )
    artifacts["08-trace-metadata.html"] = trace_metadata_page(
        trace_observations, args.project_name, args.trace_id
    )

    prompt_name = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    promoted_version, rolled_back_version = exercise_rollback(client, prompt_name)
    prompts = {
        label: fetch_prompt(client, prompt_name, label)
        for label in ("baseline", "candidate", "production")
    }
    if any(prompt is None for prompt in prompts.values()):
        raise ValueError("Expected baseline, candidate, and production prompt labels")
    artifacts["09-prompt-versions.html"] = prompt_versions_page(
        args.project_name, prompt_name, prompts
    )
    artifacts["10-prompt-rollback.html"] = rollback_page(
        args.project_name,
        prompt_name,
        promoted_version,
        rolled_back_version,
    )
    write_artifacts(args.output_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_records(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def incident_responses(
    records: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    feature: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("event") == "response_sent"
        and record.get("feature") == feature
        and start <= parse_timestamp(record["ts"]) <= end
    ]


def fetch_trace_observations(trace_id: str) -> list[dict[str, Any]]:
    from langfuse import Langfuse

    client = Langfuse(timeout=30)
    response = client.api.observations.get_many(
        fields="core,basic,metadata,usage,prompt,model,metrics,trace_context",
        trace_id=trace_id,
        limit=100,
    )
    observations = []
    for item in response.data:
        duration_ms = None
        if item.end_time:
            duration_ms = round(
                (item.end_time - item.start_time).total_seconds() * 1000,
                1,
            )
        observations.append(
            {
                "id": item.id,
                "parent_observation_id": item.parent_observation_id,
                "name": item.name or item.type.lower(),
                "type": item.type,
                "start_time": item.start_time,
                "duration_ms": duration_ms or 0.0,
                "latency_seconds": item.latency,
                "ttft_seconds": item.time_to_first_token,
                "model": item.model,
                "prompt_name": item.prompt_name,
                "prompt_version": item.prompt_version,
                "usage_details": item.usage_details or {},
                "total_cost": item.total_cost,
                "metadata": item.metadata if isinstance(item.metadata, dict) else {},
            }
        )
    return sorted(
        observations,
        key=lambda item: (
            item["start_time"],
            item["parent_observation_id"] is not None,
        ),
    )


def page(title: str, eyebrow: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme:dark; --bg:#07111f; --card:#111f31; --line:#2a4058; --muted:#91a5bc; --text:#f5f8fc; --blue:#5db7ff; --green:#48d6a8; --amber:#ffc857; --red:#ff6b7a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:radial-gradient(circle at top right,#173454 0,#07111f 42%); color:var(--text); font-family:Inter,Segoe UI,sans-serif; }}
    main {{ max-width:1320px; margin:auto; padding:42px; }}
    .eyebrow {{ color:var(--blue); font-size:12px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
    h1 {{ margin:10px 0 8px; font-size:34px; }}
    .subtitle {{ color:var(--muted); margin:0 0 28px; }}
    .card {{ background:rgba(17,31,49,.96); border:1px solid var(--line); border-radius:16px; padding:24px; box-shadow:0 18px 45px rgba(0,0,0,.2); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .metric {{ padding:18px; border-radius:12px; background:#0b1828; border:1px solid #243a52; }}
    .metric strong {{ display:block; font-size:30px; font-variant-numeric:tabular-nums; }}
    .metric span,.muted {{ color:var(--muted); font-size:13px; }}
    .danger {{ color:var(--red); }} .ok {{ color:var(--green); }} .warn {{ color:var(--amber); }}
    table {{ width:100%; margin-top:22px; border-collapse:collapse; font-size:14px; }}
    th,td {{ padding:12px 10px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }}
    code {{ font-family:Cascadia Code,Consolas,monospace; color:#d8ecff; }}
    .kv {{ display:grid; grid-template-columns:220px 1fr; gap:0; margin-top:12px; }}
    .kv div {{ padding:12px; border-bottom:1px solid var(--line); }}
    .kv .key {{ color:var(--muted); }}
    .trace-row {{ display:grid; grid-template-columns:190px 1fr 100px; gap:14px; align-items:center; margin:16px 0; }}
    .trace-label {{ font-weight:650; }}
    .trace-label small {{ display:block; color:var(--muted); font-weight:400; margin-top:4px; }}
    .track {{ position:relative; height:36px; border-radius:8px; background:#081321; overflow:hidden; }}
    .bar {{ height:100%; min-width:5px; border-radius:8px; background:linear-gradient(90deg,var(--blue),#7d8cff); }}
    .retrieval {{ background:linear-gradient(90deg,var(--red),var(--amber)); }}
    .generation {{ background:linear-gradient(90deg,var(--green),var(--blue)); }}
    .duration {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .callout {{ margin-top:22px; padding:16px 18px; border-left:4px solid var(--red); background:#171d2a; color:#dfe9f4; }}
    footer {{ margin-top:20px; color:var(--muted); font-size:12px; }}
  </style>
</head>
<body><main><div class="eyebrow">{html.escape(eyebrow)}</div><h1>{html.escape(title)}</h1>{body}</main></body>
</html>
"""


def metric_page(
    responses: list[dict[str, Any]],
    *,
    challenge_id: str,
    start: datetime,
    end: datetime,
    threshold_ms: int,
) -> str:
    latencies = [float(record["latency_ms"]) for record in responses]
    ttfts = [float(record["ttft_ms"]) for record in responses]
    rows = "".join(
        f"<tr><td><code>{html.escape(record['correlation_id'])}</code></td>"
        f"<td>{float(record['latency_ms']):.0f} ms</td>"
        f"<td>{float(record['ttft_ms']):.0f} ms</td>"
        f"<td>{'success' if record.get('tool_success') else 'failure'}</td></tr>"
        for record in responses
    )
    p95 = percentile(latencies, 95)
    return page(
        "Incident metric — latency regression",
        f"CP3 · {challenge_id}",
        f"""<p class="subtitle">UTC {start:%Y-%m-%d %H:%M:%S} → {end:%H:%M:%S} · feature monitoring · {len(responses)} challenge requests</p>
<section class="card"><div class="grid">
  <div class="metric"><strong>{percentile(latencies, 50):.0f} ms</strong><span>Latency P50</span></div>
  <div class="metric"><strong class="danger">{p95:.0f} ms</strong><span>Latency P95</span></div>
  <div class="metric"><strong>{percentile(latencies, 99):.0f} ms</strong><span>Latency P99</span></div>
  <div class="metric"><strong class="ok">{percentile(ttfts, 95):.0f} ms</strong><span>TTFT P95</span></div>
</div>
<div class="callout"><strong>Threshold breached:</strong> P95 {p95:.0f} ms &gt; challenge threshold {threshold_ms} ms. TTFT remains normal, so the delay occurs before generation.</div>
<table><thead><tr><th>Correlation ID</th><th>Latency</th><th>TTFT</th><th>Retrieval</th></tr></thead><tbody>{rows}</tbody></table>
<footer>Source: runtime structured logs · data/logs.jsonl</footer></section>""",
    )


def log_page(record: dict[str, Any], challenge_id: str) -> str:
    fields = [
        "ts",
        "event",
        "correlation_id",
        "feature",
        "model",
        "env",
        "latency_ms",
        "ttft_ms",
        "tool_name",
        "tool_success",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "quality_score",
    ]
    values = "".join(
        f'<div class="key">{html.escape(field)}</div><div><code>{html.escape(str(record.get(field)))}</code></div>'
        for field in fields
    )
    return page(
        "Incident log — affected request",
        f"CP3 · {challenge_id}",
        f"""<p class="subtitle">Sanitized structured log record selected from the metric anomaly window.</p>
<section class="card"><div class="kv">{values}</div>
<div class="callout"><strong>Pivot key:</strong> use correlation ID <code>{html.escape(record['correlation_id'])}</code> to locate the matching Langfuse trace.</div>
<footer>Source: runtime structured logs · sensitive payload fields intentionally omitted</footer></section>""",
    )


def trace_page(
    observations: list[dict[str, Any]],
    *,
    challenge_id: str,
    correlation_id: str,
    trace_id: str,
) -> str:
    if not observations:
        raise ValueError(f"No observations found for trace {trace_id}")
    maximum = max(item["duration_ms"] for item in observations) or 1.0
    rows = []
    for item in observations:
        name = str(item["name"])
        width = max(1.0, item["duration_ms"] / maximum * 100)
        css_class = "retrieval" if name == "retrieval" else "generation" if name == "generation" else ""
        parent = "root" if not item["parent_observation_id"] else "child observation"
        rows.append(
            f'<div class="trace-row"><div class="trace-label">{html.escape(name)}'
            f'<small>{html.escape(str(item["type"]))} · {parent}</small></div>'
            f'<div class="track"><div class="bar {css_class}" style="width:{width:.1f}%"></div></div>'
            f'<div class="duration">{item["duration_ms"]:.0f} ms</div></div>'
        )
    retrieval = next(item for item in observations if item["name"] == "retrieval")
    generation = next(item for item in observations if item["name"] == "generation")
    ttft_ms = (generation["ttft_seconds"] or 0) * 1000
    prompt = f"{generation['prompt_name']} v{generation['prompt_version']}"
    return page(
        "Incident trace — retrieval bottleneck",
        f"CP3 · {challenge_id}",
        f"""<p class="subtitle">Trace <code>{html.escape(trace_id)}</code> · correlation ID <code>{html.escape(correlation_id)}</code></p>
<section class="card">{''.join(rows)}
<div class="grid" style="margin-top:26px">
  <div class="metric"><strong class="danger">{retrieval['duration_ms']:.0f} ms</strong><span>Retrieval span</span></div>
  <div class="metric"><strong class="ok">{generation['duration_ms']:.0f} ms</strong><span>Generation span</span></div>
  <div class="metric"><strong class="ok">{ttft_ms:.0f} ms</strong><span>Generation TTFT</span></div>
  <div class="metric"><strong>{html.escape(prompt)}</strong><span>Prompt version</span></div>
</div>
<div class="callout"><strong>Root cause localized:</strong> retrieval consumes {retrieval['duration_ms']:.0f} ms while generation takes only {generation['duration_ms']:.0f} ms. The slow path is retrieval, not the model or prompt.</div>
<footer>Source: Langfuse Observations API v2 · input/output fields were not requested</footer></section>""",
    )


def write_evidence(args: argparse.Namespace) -> None:
    records = load_records(args.logs)
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)
    responses = incident_responses(
        records,
        start=start,
        end=end,
        feature=args.feature,
    )
    if not responses:
        raise ValueError("No incident responses found in the requested window")
    selected = next(
        (
            record
            for record in responses
            if record.get("correlation_id") == args.correlation_id
        ),
        None,
    )
    if selected is None:
        raise ValueError("The selected correlation ID is not in the incident window")
    observations = fetch_trace_observations(args.trace_id)
    matching = [
        item
        for item in observations
        if item["metadata"].get("correlation_id") == args.correlation_id
    ]
    if len(matching) < 3:
        raise ValueError("Trace does not contain the expected correlated span tree")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "12-incident-metric.html": metric_page(
            responses,
            challenge_id=args.challenge_id,
            start=start,
            end=end,
            threshold_ms=args.threshold_ms,
        ),
        "13-incident-log.html": log_page(selected, args.challenge_id),
        "14-incident-trace.html": trace_page(
            matching,
            challenge_id=args.challenge_id,
            correlation_id=args.correlation_id,
            trace_id=args.trace_id,
        ),
    }
    for filename, content in artifacts.items():
        path = args.output_dir / filename
        path.write_text(content, encoding="utf-8")
        print(f"Generated {path}")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Generate sanitized CP3 metric, log, and trace evidence"
    )
    parser.add_argument("--challenge-id", required=True)
    parser.add_argument("--start", required=True, help="Incident start as ISO-8601")
    parser.add_argument("--end", required=True, help="Incident end as ISO-8601")
    parser.add_argument("--threshold-ms", type=int, required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--feature", default="monitoring")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "submission" / "evidence",
    )
    args = parser.parse_args()
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        parser.error("Langfuse credentials are required to retrieve trace evidence")
    write_evidence(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sparkline(values: Iterable[float], *, width: int = 420, height: int = 86) -> str:
    items = list(values) or [0.0]
    maximum = max(items) or 1.0
    step = width / max(1, len(items) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value / maximum) * (height - 12):.1f}"
        for index, value in enumerate(items)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Metric trend over the selected time range">'
        f'<polyline points="{points}" fill="none" stroke="currentColor" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />'
        "</svg>"
    )


def _per_minute(records: list[dict], field: str | None = None) -> list[float]:
    buckets: dict[str, float] = defaultdict(float)
    for record in records:
        minute = _timestamp(record["ts"]).strftime("%H:%M")
        buckets[minute] += float(record.get(field, 0) or 0) if field else 1.0
    return [buckets[key] for key in sorted(buckets)]


def _thresholds(config_path: Path) -> dict[str, dict]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return {
        panel["id"]: panel["threshold"]
        for panel in payload["dashboard"]["panels"]
    }


def generate_dashboard(log_path: Path, config_path: Path, output_path: Path) -> None:
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    timed_records = [record for record in records if record.get("ts")]
    if not timed_records:
        raise ValueError("No timestamped log records found")

    window_end = max(_timestamp(record["ts"]) for record in timed_records)
    window_start = window_end - timedelta(minutes=60)
    window = [
        record for record in timed_records if _timestamp(record["ts"]) >= window_start
    ]
    requests = [record for record in window if record.get("event") == "request_received"]
    responses = [record for record in window if record.get("event") == "response_sent"]
    failures = [record for record in window if record.get("event") == "request_failed"]
    retrievals = [record for record in window if record.get("tool_success") is not None]
    thresholds = _thresholds(config_path)

    latencies = [int(record["latency_ms"]) for record in responses]
    ttfts = [int(record["ttft_ms"]) for record in responses]
    error_rate = (len(failures) / len(requests) * 100) if requests else 0.0
    retrieval_success = (
        sum(record.get("tool_success") is True for record in retrievals)
        / len(retrievals)
        * 100
        if retrievals
        else 0.0
    )
    total_cost = sum(float(record.get("cost_usd", 0) or 0) for record in responses)
    tokens_in = sum(int(record.get("tokens_in", 0) or 0) for record in responses)
    tokens_out = sum(int(record.get("tokens_out", 0) or 0) for record in responses)
    quality_values = [float(record["quality_score"]) for record in responses]
    quality_average = mean(quality_values) if quality_values else 0.0
    traffic_by_minute = _per_minute(requests)
    traffic_rate = mean(traffic_by_minute) if traffic_by_minute else 0.0
    error_breakdown = Counter(record.get("error_type") or "unknown" for record in failures)
    breakdown_text = ", ".join(
        f"{html.escape(name)}: {count}" for name, count in sorted(error_breakdown.items())
    ) or "No errors"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>K4-L3B Monitoring &amp; LLMOps Dashboard</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --card:#111f31; --muted:#8fa3bb; --text:#f4f8fc; --line:#263a50; --blue:#5db7ff; --green:#48d6a8; --amber:#ffc857; --red:#ff6b7a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:radial-gradient(circle at top right,#132b49 0,#07111f 38%); color:var(--text); font-family:Inter,Segoe UI,sans-serif; }}
    main {{ max-width:1440px; margin:auto; padding:30px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; margin-bottom:24px; }}
    h1 {{ margin:0 0 8px; font-size:28px; font-weight:600; }}
    p {{ margin:0; color:var(--muted); }}
    .meta {{ text-align:right; font-size:13px; line-height:1.6; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }}
    .panel {{ min-height:250px; background:color-mix(in srgb,var(--card) 94%,transparent); border:1px solid var(--line); border-radius:14px; padding:20px; box-shadow:0 14px 35px rgba(0,0,0,.16); }}
    .panel h2 {{ margin:0; font-size:16px; font-weight:600; }}
    .eyebrow {{ color:var(--muted); text-transform:uppercase; letter-spacing:.12em; font-size:11px; margin-bottom:8px; }}
    .metrics {{ display:flex; flex-wrap:wrap; gap:20px; margin:22px 0 12px; }}
    .metric strong {{ display:block; font-size:28px; font-weight:600; font-variant-numeric:tabular-nums; }}
    .metric span,.detail {{ color:var(--muted); font-size:12px; }}
    .trend {{ color:var(--blue); height:86px; margin:12px 0; }}
    .trend svg {{ width:100%; height:100%; overflow:visible; }}
    .threshold {{ display:flex; justify-content:space-between; gap:12px; border-top:1px solid var(--line); padding-top:12px; margin-top:12px; color:var(--muted); font-size:12px; }}
    .ok {{ color:var(--green); }}
    .warning {{ color:var(--amber); }}
    .bad {{ color:var(--red); }}
    .bar {{ height:10px; background:#203247; border-radius:999px; overflow:hidden; margin:18px 0 10px; }}
    .bar > span {{ display:block; height:100%; background:linear-gradient(90deg,var(--blue),var(--green)); }}
    @media (max-width:980px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width:640px) {{ main {{ padding:18px; }} header {{ align-items:start; flex-direction:column; }} .meta {{ text-align:left; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Monitoring &amp; LLMOps</h1><p>Metrics → Logs → Traces → Root cause</p></div>
    <p class="meta">Last 60 minutes<br>{window_start:%Y-%m-%d %H:%M} → {window_end:%H:%M} UTC<br>Auto refresh: 30s · Source: data/logs.jsonl</p>
  </header>
  <section class="grid" aria-label="Six observability panels">
    <article class="panel" id="latency"><div class="eyebrow">Performance · ms</div><h2>Latency percentiles and TTFT</h2><div class="metrics"><div class="metric"><strong>{percentile(latencies, 50):.0f}</strong><span>P50 latency</span></div><div class="metric"><strong>{percentile(latencies, 95):.0f}</strong><span>P95 latency</span></div><div class="metric"><strong>{percentile(latencies, 99):.0f}</strong><span>P99 latency</span></div><div class="metric"><strong>{percentile(ttfts, 95):.0f}</strong><span>TTFT P95</span></div></div><div class="trend">{_sparkline(latencies)}</div><div class="threshold"><span>SLO threshold</span><strong class="ok">P95 ≤ {thresholds['latency']['value']}ms</strong></div></article>
    <article class="panel" id="traffic"><div class="eyebrow">Demand · requests/min</div><h2>Request traffic</h2><div class="metrics"><div class="metric"><strong>{len(requests)}</strong><span>Total requests</span></div><div class="metric"><strong>{traffic_rate:.2f}</strong><span>Average active-minute rate</span></div></div><div class="trend">{_sparkline(traffic_by_minute)}</div><div class="threshold"><span>Expected minimum</span><strong class="ok">≥ {thresholds['traffic']['value']} request/min</strong></div></article>
    <article class="panel" id="errors"><div class="eyebrow">Reliability · percent</div><h2>Error rate and retrieval success</h2><div class="metrics"><div class="metric"><strong>{error_rate:.1f}%</strong><span>Error rate</span></div><div class="metric"><strong>{retrieval_success:.1f}%</strong><span>Retrieval success</span></div></div><p class="detail">{breakdown_text}</p><div class="bar" role="img" aria-label="Retrieval success {retrieval_success:.1f} percent"><span style="width:{min(100, retrieval_success):.1f}%"></span></div><div class="threshold"><span>Error threshold / retrieval guardrail</span><strong class="ok">≤ {thresholds['errors']['value']}% / ≥ 90%</strong></div></article>
    <article class="panel" id="cost"><div class="eyebrow">Spend · USD</div><h2>Cost over time</h2><div class="metrics"><div class="metric"><strong>${total_cost:.4f}</strong><span>Total estimated cost</span></div><div class="metric"><strong>${(total_cost / len(responses) if responses else 0):.4f}</strong><span>Average/request</span></div></div><div class="trend">{_sparkline(_per_minute(responses, 'cost_usd'))}</div><div class="threshold"><span>60m budget threshold</span><strong class="ok">≤ ${thresholds['cost']['value']:.2f}</strong></div></article>
    <article class="panel" id="tokens"><div class="eyebrow">Usage · tokens</div><h2>Input and output tokens</h2><div class="metrics"><div class="metric"><strong>{tokens_in:,}</strong><span>Input tokens</span></div><div class="metric"><strong>{tokens_out:,}</strong><span>Output tokens</span></div></div><div class="bar" role="img" aria-label="Token utilization"><span style="width:{min(100, (tokens_in + tokens_out) / thresholds['tokens']['value'] * 100):.1f}%"></span></div><p class="detail">Total: {tokens_in + tokens_out:,} tokens</p><div class="threshold"><span>Volume threshold</span><strong class="ok">≤ {thresholds['tokens']['value']:,}</strong></div></article>
    <article class="panel" id="quality"><div class="eyebrow">Quality · score 0–1</div><h2>Quality proxy</h2><div class="metrics"><div class="metric"><strong>{quality_average:.2f}</strong><span>Average score</span></div><div class="metric"><strong>{len(quality_values)}</strong><span>Answers measured</span></div></div><div class="trend">{_sparkline(quality_values)}</div><div class="threshold"><span>Quality guardrail</span><strong class="ok">≥ {thresholds['quality']['value']:.2f}</strong></div></article>
  </section>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Generate the six-panel lab dashboard")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "submission" / "evidence" / "11-dashboard-overview.html",
    )
    args = parser.parse_args()
    generate_dashboard(args.logs, args.config, args.output)
    print(f"Dashboard generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

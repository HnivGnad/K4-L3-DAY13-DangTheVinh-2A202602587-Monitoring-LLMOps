from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent import LabAgent
from app.cli import configure_utf8_stdio
from app.tracing import get_langfuse_client, tracing_enabled


QUERIES = REPO_ROOT / "data" / "sample_queries.jsonl"


def main() -> int:
    configure_utf8_stdio()
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Generate sanitized Day 13 traces for one managed prompt label."
    )
    parser.add_argument(
        "--label",
        choices=("baseline", "candidate", "production"),
        default=os.getenv("LANGFUSE_PROMPT_LABEL", "production"),
    )
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be greater than zero")
    if not tracing_enabled():
        print("Tracing is disabled. Check LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.")
        return 1

    os.environ["LANGFUSE_PROMPT_LABEL"] = args.label
    payloads = [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    agent = LabAgent()
    for index in range(args.count):
        payload = payloads[index % len(payloads)]
        correlation_id = f"req-{uuid.uuid4().hex[:8]}"
        result = agent.run(
            user_id=payload["user_id"],
            feature=payload["feature"],
            session_id=payload["session_id"],
            message=payload["message"],
            correlation_id=correlation_id,
        )
        print(
            f"{index + 1:02d}/{args.count} label={args.label} "
            f"correlation_id={correlation_id} latency_ms={result.latency_ms}"
        )

    get_langfuse_client().flush()
    print(f"Flushed {args.count} traces for label={args.label}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

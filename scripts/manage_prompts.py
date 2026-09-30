from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE
from app.tracing import get_langfuse_client


CANDIDATE_PROMPT_TEMPLATE = (
    DEFAULT_PROMPT_TEMPLATE
    + "\nAnswer concisely and use only evidence from the supplied docs."
)
MANAGED_LABELS = ("baseline", "candidate", "production")


def fetch_prompt(client: Any, name: str, label: str):
    try:
        return client.get_prompt(
            name,
            label=label,
            type="text",
            cache_ttl_seconds=0,
            fetch_timeout_seconds=5,
            max_retries=0,
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status_code == 404 or getattr(response, "status_code", None) == 404:
            return None
        raise


def print_status(client: Any, name: str) -> dict[str, Any | None]:
    prompts = {label: fetch_prompt(client, name, label) for label in MANAGED_LABELS}
    print(f"Prompt: {name}")
    for label, prompt in prompts.items():
        version = str(prompt.version) if prompt is not None else "missing"
        print(f"- {label}: {version}")
    return prompts


def setup_versions(client: Any, name: str) -> None:
    prompts = print_status(client, name)
    if prompts["baseline"] is None:
        client.create_prompt(
            name=name,
            type="text",
            prompt=DEFAULT_PROMPT_TEMPLATE,
            labels=["baseline", "production"],
        )
        print("Created baseline prompt and assigned baseline + production labels.")
    if prompts["candidate"] is None:
        client.create_prompt(
            name=name,
            type="text",
            prompt=CANDIDATE_PROMPT_TEMPLATE,
            labels=["candidate"],
        )
        print("Created candidate prompt and assigned candidate label.")
    print_status(client, name)


def move_production_label(client: Any, name: str, target_label: str) -> None:
    target = fetch_prompt(client, name, target_label)
    if target is None:
        raise RuntimeError(
            f"Prompt label '{target_label}' does not exist. Run the setup command first."
        )
    client.update_prompt(
        name=name,
        version=target.version,
        new_labels=[target_label, "production"],
    )
    print(f"production -> {name} v{target.version} ({target_label})")
    print_status(client, name)


def main() -> int:
    configure_utf8_stdio()
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Create, inspect, promote, and roll back Day 13 Langfuse prompts."
    )
    parser.add_argument(
        "action", choices=("status", "setup", "promote", "rollback")
    )
    args = parser.parse_args()

    client = get_langfuse_client()
    try:
        authenticated = client.auth_check()
    except Exception as exc:
        print(f"Cannot reach Langfuse: {type(exc).__name__}")
        return 2
    if not authenticated:
        print("Langfuse authentication failed. Check the project keys in .env.")
        return 1

    prompt_name = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    try:
        if args.action == "status":
            print_status(client, prompt_name)
        elif args.action == "setup":
            setup_versions(client, prompt_name)
        elif args.action == "promote":
            move_production_label(client, prompt_name, "candidate")
        else:
            move_production_label(client, prompt_name, "baseline")
    except Exception as exc:
        print(f"Langfuse prompt operation failed: {type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import resolve_prompt
from .tracing import get_langfuse_client, observe, propagate_attributes, tracing_enabled


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(name="lab-agent-run", as_type="agent", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str,
    ) -> AgentResult:
        langfuse_client = get_langfuse_client()
        trace_is_enabled = tracing_enabled()
        with propagate_attributes(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            trace_name="day13-agent-request",
            environment=os.getenv("APP_ENV", "dev"),
            metadata={
                "feature": feature,
                "model": self.model,
                "correlation_id": correlation_id,
            },
        ):
            started = time.perf_counter()
            retrieval_context = (
                langfuse_client.start_as_current_observation(
                    name="retrieval",
                    as_type="retriever",
                    input={"query_preview": summarize_text(message)},
                    metadata={"correlation_id": correlation_id},
                )
                if trace_is_enabled
                else nullcontext()
            )
            with retrieval_context as retrieval_observation:
                try:
                    docs = retrieve(message)
                except Exception:
                    metrics.record_retrieval(success=False)
                    raise
                metrics.record_retrieval(success=True)
                if retrieval_observation is not None:
                    retrieval_observation.update(
                        output={
                            "doc_count": len(docs),
                            "document_previews": [summarize_text(doc) for doc in docs],
                        }
                    )

            prompt = resolve_prompt(
                langfuse_client,
                feature=feature,
                docs=docs,
                message=message,
                enabled=trace_is_enabled,
            )
            if trace_is_enabled:
                langfuse_client.update_current_span(
                    metadata={
                        "doc_count": len(docs),
                        "query_preview": summarize_text(message),
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                        "prompt_source": prompt.source,
                        "prompt_fetch_error": prompt.fetch_error or "",
                    },
                    version=prompt.version,
                )

            prompt_context = (
                propagate_attributes(prompt=prompt.managed_prompt)
                if trace_is_enabled
                else nullcontext()
            )
            generation_context = (
                langfuse_client.start_as_current_observation(
                    name="generation",
                    as_type="generation",
                    model=self.model,
                    input={"prompt_preview": summarize_text(prompt.text)},
                    metadata={
                        "correlation_id": correlation_id,
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                    },
                    prompt=prompt.managed_prompt,
                )
                if trace_is_enabled
                else nullcontext()
            )
            generation_started_at = datetime.now(timezone.utc)
            with prompt_context:
                with generation_context as generation_observation:
                    response = self.llm.generate(prompt.text)
                    cost_details = self._estimate_cost_details(
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    )
                    if generation_observation is not None:
                        generation_observation.update(
                            output={"answer_preview": summarize_text(response.text)},
                            completion_start_time=generation_started_at
                            + timedelta(milliseconds=response.ttft_ms),
                            usage_details={
                                "input": response.usage.input_tokens,
                                "output": response.usage.output_tokens,
                                "total": response.usage.input_tokens
                                + response.usage.output_tokens,
                            },
                            cost_details=cost_details,
                            metadata={"ttft_ms": response.ttft_ms},
                        )
            quality_score = self._heuristic_quality(message, response.text, docs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            cost_usd = cost_details["total"]

        metrics.record_request(
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
        )

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return self._estimate_cost_details(tokens_in, tokens_out)["total"]

    def _estimate_cost_details(self, tokens_in: int, tokens_out: int) -> dict[str, float]:
        input_cost = round((tokens_in / 1_000_000) * 3, 6)
        output_cost = round((tokens_out / 1_000_000) * 15, 6)
        return {
            "input": input_cost,
            "output": output_cost,
            "total": round(input_cost + output_cost, 6),
        }

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)

from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.observations: list[RecordingObservation] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = RecordingObservation(kwargs)
        self.observations.append(observation)
        yield observation


class RecordingObservation:
    def __init__(self, started_with: dict) -> None:
        self.started_with = started_with
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[-1]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain traces",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert propagated[-1]["prompt"] is client.prompt

    retrieval, generation = client.observations
    assert retrieval.started_with["name"] == "retrieval"
    assert retrieval.started_with["as_type"] == "retriever"
    assert retrieval.started_with["input"] == {"query_preview": "Explain traces"}
    assert retrieval.updates[-1]["output"]["doc_count"] == 1

    assert generation.started_with["name"] == "generation"
    assert generation.started_with["as_type"] == "generation"
    assert generation.started_with["model"] == "claude-sonnet-4-5"
    assert generation.started_with["prompt"] is client.prompt
    generation_update = generation.updates[-1]
    assert generation_update["usage_details"]["total"] == (
        generation_update["usage_details"]["input"]
        + generation_update["usage_details"]["output"]
    )
    assert generation_update["cost_details"]["total"] > 0
    assert "completion_start_time" in generation_update

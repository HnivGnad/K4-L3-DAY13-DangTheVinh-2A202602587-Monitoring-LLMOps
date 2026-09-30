from app import metrics
from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_snapshot_exposes_error_and_retrieval_rates(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "TRAFFIC", 10)
    monkeypatch.setattr(metrics, "ERRORS", metrics.Counter({"RuntimeError": 2}))
    monkeypatch.setattr(metrics, "RETRIEVAL_ATTEMPTS", 10)
    monkeypatch.setattr(metrics, "RETRIEVAL_SUCCESSES", 9)

    result = metrics.snapshot()

    assert result["error_rate_pct"] == 20.0
    assert result["retrieval_success_rate_pct"] == 90.0

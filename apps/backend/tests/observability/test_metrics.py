import json
import time

import pytest

from core.observability.metrics import put_metric, timing, gauge, NAMESPACE


def test_put_metric_emits_emf_json(capsys):
    """put_metric should emit a single JSON line with _aws.CloudWatchMetrics envelope."""
    put_metric("container.provision", value=1.0, unit="Count", dimensions={"status": "ok"})
    output = capsys.readouterr().out.strip()
    data = json.loads(output)
    assert "_aws" in data
    assert data["_aws"]["CloudWatchMetrics"][0]["Namespace"] == NAMESPACE
    assert data["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "container.provision"
    assert data["container.provision"] == 1.0
    assert data["status"] == "ok"


def test_put_metric_auto_injects_env_and_service(capsys):
    """env and service dimensions should be auto-injected."""
    from unittest.mock import patch

    with patch("core.observability.metrics._get_env", return_value="dev"), \
         patch("core.observability.metrics._get_service", return_value="isol8-backend"):
        put_metric("test.metric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["env"] == "dev"
    assert data["service"] == "isol8-backend"


def test_put_metric_rejects_high_cardinality_dimensions():
    """user_id, container_id, request_id must not be used as metric dimensions."""
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"user_id": "u123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"container_id": "c123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"request_id": "r123"})


def test_timing_context_manager_emits_latency(capsys):
    """timing() should emit a metric with elapsed milliseconds."""
    with timing("container.lifecycle.latency", {"op": "start"}):
        time.sleep(0.01)  # ~10ms
    data = json.loads(capsys.readouterr().out.strip())
    assert data["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "Milliseconds"
    assert data["container.lifecycle.latency"] >= 10  # at least 10ms


def test_gauge_emits_value(capsys):
    """gauge() should emit the given value."""
    gauge("gateway.connection.open", 42)
    data = json.loads(capsys.readouterr().out.strip())
    assert data["gateway.connection.open"] == 42

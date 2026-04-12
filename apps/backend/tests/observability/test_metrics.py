"""Tests for core/observability/metrics.py — EMF emitter."""

import json
import time
from unittest.mock import patch

import pytest

from core.observability.metrics import NAMESPACE, gauge, put_metric, timing


def test_put_metric_emits_valid_emf_json(capsys):
    """Output should be a single JSON line with _aws.CloudWatchMetrics envelope."""
    put_metric("container.provision", dimensions={"status": "ok"})
    line = capsys.readouterr().out.strip()
    data = json.loads(line)

    assert "_aws" in data
    cw = data["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == NAMESPACE
    assert cw["Metrics"][0]["Name"] == "container.provision"
    assert cw["Metrics"][0]["Unit"] == "Count"
    assert data["container.provision"] == 1.0
    assert data["status"] == "ok"


def test_put_metric_auto_injects_env_and_service(capsys):
    """Every metric gets env + service dimensions automatically."""
    with patch("core.observability.metrics._get_env", return_value="dev"):
        put_metric("test.metric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["env"] == "dev"
    assert data["service"] == "isol8-backend"
    assert "env" in data["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert "service" in data["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]


def test_put_metric_rejects_high_cardinality_dimensions():
    """user_id, container_id, request_id, owner_id must raise ValueError."""
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"user_id": "u123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"container_id": "c123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"request_id": "r123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"owner_id": "o123"})


def test_timing_emits_latency_in_milliseconds(capsys):
    """timing() should emit a Milliseconds metric with elapsed time."""
    with timing("container.lifecycle.latency", {"op": "start"}):
        time.sleep(0.01)
    data = json.loads(capsys.readouterr().out.strip())
    assert data["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "Milliseconds"
    assert data["container.lifecycle.latency"] >= 10
    assert data["op"] == "start"


def test_gauge_emits_value(capsys):
    """gauge() should emit the exact value passed."""
    gauge("gateway.connection.open", 42)
    data = json.loads(capsys.readouterr().out.strip())
    assert data["gateway.connection.open"] == 42


def test_put_metric_default_value_is_one(capsys):
    """Calling put_metric without a value should default to 1.0."""
    put_metric("chat.message.count")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["chat.message.count"] == 1.0

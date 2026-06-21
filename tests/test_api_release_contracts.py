"""T48.8 release contracts for model and portfolio API routes."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import models, portfolio
from src.api.schemas.release_contracts import PortfolioCheckRequestV1


class _ModelIndex:
    def __init__(self, version: dict | None = None):
        self.version = version

    def list_versions(self, *, limit: int, market: str | None = None) -> list[dict]:
        return []

    def get_version(self, artifact_id: str) -> dict | None:
        return self.version if self.version and self.version["id"] == artifact_id else None


class _ModelService:
    def __init__(
        self,
        *,
        promotion: dict | None = None,
        delete_result: bool = True,
        error: Exception | None = None,
    ):
        self.promotion = promotion or {"ok": True, "gate_failures": []}
        self.delete_result = delete_result
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def get_model_details(self, artifact_id: str) -> dict:
        if self.error:
            raise self.error
        self.calls.append(("details", artifact_id))
        return {"id": artifact_id}

    def promote_model(self, artifact_id: str, stage: str) -> dict:
        if self.error:
            raise self.error
        self.calls.append(("promote", artifact_id, stage))
        return self.promotion

    def delete_model(self, artifact_id: str) -> bool:
        if self.error:
            raise self.error
        self.calls.append(("delete", artifact_id))
        return self.delete_result


@pytest.fixture
def model_client() -> TestClient:
    app = FastAPI()
    app.include_router(models.router, prefix="/api/models")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def portfolio_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(
        portfolio,
        "get_model_index",
        lambda: _ModelIndex(
            {
                "id": "model-abcdef123456",
                "market": "us",
                "snapshot_id": "snapshot-abcdef123456",
            }
        ),
        raising=False,
    )
    artifact_path = tmp_path / "portfolio-20260620.json"
    artifact_path.write_text(
        """{
            "portfolio_artifact_id": "portfolio-20260620",
            "model_artifact_id": "model-abcdef123456",
            "data_snapshot_id": "snapshot-abcdef123456",
            "market": "us",
            "positions": {"AAPL": 0.5, "MSFT": 0.5}
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        portfolio,
        "_portfolio_artifact_candidates",
        lambda _artifact_id: (artifact_path,),
        raising=False,
    )
    app = FastAPI()
    app.include_router(portfolio.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


def _portfolio_payload(**updates) -> dict:
    payload = {
        "schema_version": "v1",
        "portfolio_artifact_id": "portfolio-20260620",
        "model_artifact_id": "model-abcdef123456",
        "data_snapshot_id": "snapshot-abcdef123456",
        "positions": {"AAPL": 0.6, "MSFT": 0.4},
        "market": "us",
        "portfolio_value": 100_000,
    }
    payload.update(updates)
    return payload


def _market_data(*, include_factor: bool, include_turnover: bool, include_qlib: bool):
    market_data: dict = {
        "portfolio_value": 100_000,
        "industry_map": {"AAPL": "Technology", "MSFT": "Technology"},
    }
    status = {"industry_map": "provided"}
    if include_factor:
        market_data["factor_exposures"] = {
            "AAPL": {"momentum": 0.5},
            "MSFT": {"momentum": -0.2},
        }
        status["factor_exposures"] = "provided"
    else:
        status["factor_exposures"] = "unavailable"
    if include_turnover:
        market_data["prev_positions"] = {"AAPL": 0.5, "MSFT": 0.5}
        status["prev_positions"] = "provided"
    else:
        status["prev_positions"] = "unavailable"
    if include_qlib:
        returns = pd.DataFrame({"AAPL": [0.01, -0.01], "MSFT": [0.02, 0.01]})
        volumes = pd.DataFrame({"AAPL": [2_000_000, 2_100_000], "MSFT": [1_900_000, 2_000_000]})
        prices = pd.DataFrame({"AAPL": [200.0, 201.0], "MSFT": [400.0, 402.0]})
        market_data.update(
            returns_df=returns,
            daily_returns=returns.mean(axis=1).tolist(),
            volume_df=volumes,
            price_df=prices,
        )
        status.update(returns="loaded", volume="loaded", price="loaded")
    else:
        status.update(returns="unavailable", volume="unavailable", price="unavailable")
    return market_data, status, []


def _install_collector_data(monkeypatch, fields: dict[str, list[str]]) -> None:
    from qlib.data import D

    from src.data.snapshot import DataSnapshot

    monkeypatch.setattr(
        DataSnapshot,
        "resolve_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            manifest=SimpleNamespace(storage_uri="exact-provider")
        ),
    )
    monkeypatch.setattr("src.common.qlib_init.build_qlib_init_cfg", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("src.common.qlib_init.safe_qlib_init", lambda *_args, **_kwargs: None)

    def _features(_symbols, expressions, **_kwargs):
        expression = expressions[0]
        available = fields[expression]
        if not available:
            return pd.DataFrame()
        index = pd.MultiIndex.from_product(
            [available, pd.to_datetime(["2026-06-18", "2026-06-19"])],
            names=["instrument", "datetime"],
        )
        values = [1.0 + offset for offset in range(len(index))]
        return pd.DataFrame({expression: values}, index=index)

    monkeypatch.setattr(D, "features", _features, raising=False)


def _collector_request(**updates) -> PortfolioCheckRequestV1:
    payload = _portfolio_payload(
        industry_map={"AAPL": "Technology", "MSFT": "Technology"},
        factor_exposures={
            "AAPL": {"momentum": 0.5},
            "MSFT": {"momentum": -0.2},
        },
        prev_positions={"AAPL": 0.5, "MSFT": 0.5},
    )
    payload.update(updates)
    return PortfolioCheckRequestV1.model_validate(payload)


def test_model_health_static_route_precedes_dynamic_route(model_client, monkeypatch):
    row = {
        "run_id": "run-1",
        "market": "us",
        "created_at": datetime.now().isoformat(),
    }

    class _Connection:
        def execute(self, _query):
            return self

        def fetchone(self):
            return row

    index = _ModelIndex()
    index._connect = lambda: nullcontext(_Connection())  # type: ignore[attr-defined]
    monkeypatch.setattr(models, "get_model_index", lambda: index)
    monkeypatch.setattr(
        models,
        "_check_prediction_freshness",
        lambda *_args: {"exists": True, "age_days": 0, "coverage": 2},
    )
    monkeypatch.setattr(models, "_check_qlib_data", lambda: {"available": True})

    response = model_client.get("/api/models/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_model_health_stale_artifacts_are_degraded(model_client, monkeypatch):
    row = {
        "run_id": "run-1",
        "market": "us",
        "created_at": datetime.now().isoformat(),
    }

    class _Connection:
        def execute(self, _query):
            return self

        def fetchone(self):
            return row

    index = _ModelIndex()
    index._connect = lambda: nullcontext(_Connection())  # type: ignore[attr-defined]
    monkeypatch.setattr(models, "get_model_index", lambda: index)
    monkeypatch.setattr(
        models,
        "_check_prediction_freshness",
        lambda *_args: {"exists": True, "age_days": 8, "coverage": 2},
    )
    monkeypatch.setattr(models, "_check_qlib_data", lambda: {"available": True})

    response = model_client.get("/api/models/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["code"] == "MODEL_HEALTH_DEGRADED"


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "market=invalid"])
def test_model_list_parameters_are_bounded(model_client, monkeypatch, query):
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex())

    response = model_client.get(f"/api/models?{query}")

    assert response.status_code == 422
    assert response.json()["code"] == "API_VALIDATION_ERROR"


def test_model_identifier_rejects_path_characters(model_client):
    response = model_client.get("/api/models/bad%24id")

    assert response.status_code == 422
    assert response.json()["code"] == "API_VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "v1", "artifact_id": "model-1", "stage": "ROOT"},
        {
            "schema_version": "v1",
            "artifact_id": "model-1",
            "stage": "RECOMMENDED",
            "force": True,
        },
        {"schema_version": "v2", "artifact_id": "model-1", "stage": "RECOMMENDED"},
        {"schema_version": "v1", "stage": "RECOMMENDED"},
    ],
)
def test_model_mutation_contract_rejects_invalid_payloads(model_client, payload):
    response = model_client.post("/api/models/promote", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "API_VALIDATION_ERROR"


def test_model_promotion_requires_existing_artifact(model_client, monkeypatch):
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex())

    response = model_client.post(
        "/api/models/promote",
        json={"schema_version": "v1", "artifact_id": "missing-model", "stage": "RECOMMENDED"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "MODEL_ARTIFACT_NOT_FOUND"


def test_model_promotion_gate_failure_is_conflict(model_client, monkeypatch):
    artifact = {"id": "model-1"}
    service = _ModelService(promotion={"ok": False, "gate_failures": ["missing metrics"]})
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex(artifact))
    monkeypatch.setattr(models, "get_model_service", lambda: service)

    response = model_client.post(
        "/api/models/promote",
        json={"schema_version": "v1", "artifact_id": "model-1", "stage": "RECOMMENDED"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "MODEL_PROMOTION_CONFLICT"
    assert response.json()["detail"]["gate_failures"] == ["missing metrics"]


def test_model_promotion_success_uses_exact_artifact(model_client, monkeypatch):
    artifact = {"id": "model-1"}
    service = _ModelService()
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex(artifact))
    monkeypatch.setattr(models, "get_model_service", lambda: service)

    response = model_client.post(
        "/api/models/promote",
        json={"schema_version": "v1", "artifact_id": "model-1", "stage": "STAGING"},
    )

    assert response.status_code == 200
    assert response.json()["artifact_id"] == "model-1"
    assert service.calls == [("promote", "model-1", "STAGING")]


def test_model_delete_service_rejection_is_conflict(model_client, monkeypatch):
    artifact = {"id": "model-1"}
    service = _ModelService(delete_result=False)
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex(artifact))
    monkeypatch.setattr(models, "get_model_service", lambda: service)

    response = model_client.post(
        "/api/models/delete",
        json={"schema_version": "v1", "artifact_id": "model-1"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "MODEL_DELETE_CONFLICT"


def test_model_mutation_internal_failure_is_stable(model_client, monkeypatch):
    artifact = {"id": "model-1"}
    monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex(artifact))
    monkeypatch.setattr(
        models,
        "get_model_service",
        lambda: _ModelService(error=RuntimeError("database unavailable")),
    )

    response = model_client.post(
        "/api/models/delete",
        json={"schema_version": "v1", "artifact_id": "model-1"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "API_INTERNAL_ERROR"
    assert "database unavailable" not in response.text


@pytest.mark.parametrize(
    "updates",
    [
        {"market": "crypto"},
        {"unexpected": True},
        {"schema_version": "v2"},
        {"portfolio_artifact_id": "../latest"},
        {"model_artifact_id": None},
        {"data_snapshot_id": None},
        {"positions": {}},
    ],
)
def test_portfolio_contract_rejects_invalid_inputs(portfolio_client, updates):
    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload(**updates))

    assert response.status_code == 422
    assert response.json()["code"] == "API_VALIDATION_ERROR"


def test_portfolio_contract_rejects_more_than_500_positions(portfolio_client):
    positions = {f"S{index:03d}": 0.001 for index in range(501)}

    response = portfolio_client.post(
        "/api/portfolio/check",
        json=_portfolio_payload(positions=positions),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "API_VALIDATION_ERROR"


def test_portfolio_requires_resolvable_model_identity(portfolio_client, monkeypatch):
    monkeypatch.setattr(portfolio, "get_model_index", lambda: _ModelIndex(), raising=False)

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 404
    assert response.json()["code"] == "MODEL_ARTIFACT_NOT_FOUND"


def test_portfolio_requires_resolvable_portfolio_identity(portfolio_client, monkeypatch, tmp_path):
    (tmp_path / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        portfolio,
        "_portfolio_artifact_candidates",
        lambda artifact_id: (tmp_path / "missing" / f"{artifact_id}.json",),
        raising=False,
    )

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 404
    assert response.json()["code"] == "PORTFOLIO_ARTIFACT_NOT_FOUND"


def test_portfolio_requires_resolvable_snapshot_identity(portfolio_client, monkeypatch):
    def _missing(_request):
        raise FileNotFoundError

    monkeypatch.setattr(portfolio, "_collect_portfolio_market_data", _missing, raising=False)

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 404
    assert response.json()["code"] == "DATA_SNAPSHOT_NOT_FOUND"


def test_portfolio_rejects_conflicting_artifact_bindings(portfolio_client, monkeypatch):
    monkeypatch.setattr(
        portfolio,
        "get_model_index",
        lambda: _ModelIndex(
            {
                "id": "model-abcdef123456",
                "market": "cn",
                "snapshot_id": "different-snapshot",
            }
        ),
        raising=False,
    )

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 409
    assert response.json()["code"] == "ARTIFACT_IDENTITY_CONFLICT"


def test_real_collector_missing_price_cannot_complete_liquidity(monkeypatch):
    _install_collector_data(
        monkeypatch,
        {
            "$close/Ref($close, 1) - 1": ["AAPL", "MSFT"],
            "$volume": ["AAPL", "MSFT"],
            "$close": [],
        },
    )

    _market_data_result, data_status, _warnings = portfolio._collect_portfolio_market_data(
        _collector_request()
    )
    status, performed, skipped = portfolio._check_execution_status(data_status)

    assert data_status["price"] == "empty"
    assert status == "partial"
    assert "liquidity_capacity" not in performed
    assert {item["check"] for item in skipped} == {"liquidity_capacity"}


def test_real_collector_inferred_segment_is_not_completed_industry_check(monkeypatch):
    _install_collector_data(
        monkeypatch,
        {
            "$close/Ref($close, 1) - 1": ["AAPL", "MSFT"],
            "$volume": ["AAPL", "MSFT"],
            "$close": ["AAPL", "MSFT"],
        },
    )

    _market_data_result, data_status, _warnings = portfolio._collect_portfolio_market_data(
        _collector_request(industry_map=None)
    )
    status, performed, skipped = portfolio._check_execution_status(data_status)

    assert data_status["industry_map"] == "auto_segment"
    assert status == "partial"
    assert "industry_concentration" not in performed
    assert {item["check"] for item in skipped} == {"industry_concentration"}


def test_real_collector_partial_symbol_coverage_is_fail_closed(monkeypatch):
    _install_collector_data(
        monkeypatch,
        {
            "$close/Ref($close, 1) - 1": ["AAPL", "MSFT"],
            "$volume": ["AAPL", "MSFT"],
            "$close": ["AAPL"],
        },
    )

    _market_data_result, data_status, warnings = portfolio._collect_portfolio_market_data(
        _collector_request()
    )
    status, performed, skipped = portfolio._check_execution_status(data_status)

    assert data_status["price"] == "partial"
    assert any("MSFT" in warning for warning in warnings)
    assert status == "partial"
    assert "liquidity_capacity" not in performed
    assert {item["check"] for item in skipped} == {"liquidity_capacity"}


def test_portfolio_ready_requires_all_checks(portfolio_client, monkeypatch):
    monkeypatch.setattr(
        portfolio,
        "_collect_portfolio_market_data",
        lambda _request: _market_data(
            include_factor=True, include_turnover=True, include_qlib=True
        ),
        raising=False,
    )

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "ready"
    assert body["skipped_checks"] == []
    assert body["artifact_identity"]["model_artifact_id"] == "model-abcdef123456"


def test_portfolio_partial_reports_skipped_checks(portfolio_client, monkeypatch):
    monkeypatch.setattr(
        portfolio,
        "_collect_portfolio_market_data",
        lambda _request: _market_data(
            include_factor=True, include_turnover=False, include_qlib=True
        ),
        raising=False,
    )

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "partial"
    assert body["code"] == "PORTFOLIO_CHECK_PARTIAL"
    assert {item["check"] for item in body["skipped_checks"]} == {"turnover_cost"}


def test_portfolio_blocked_uses_service_unavailable(portfolio_client, monkeypatch):
    monkeypatch.setattr(
        portfolio,
        "_collect_portfolio_market_data",
        lambda _request: _market_data(
            include_factor=False, include_turnover=False, include_qlib=False
        ),
        raising=False,
    )

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert body["code"] == "PORTFOLIO_CHECK_BLOCKED"
    assert len(body["skipped_checks"]) == 5


def test_portfolio_internal_failure_is_stable(portfolio_client, monkeypatch):
    def _raise(_request):
        raise RuntimeError("secret provider path")

    monkeypatch.setattr(portfolio, "_collect_portfolio_market_data", _raise, raising=False)

    response = portfolio_client.post("/api/portfolio/check", json=_portfolio_payload())

    assert response.status_code == 500
    assert response.json()["code"] == "API_INTERNAL_ERROR"
    assert "secret provider path" not in response.text


def test_release_routes_inherit_basic_auth_context():
    from api_server import app

    client = TestClient(app, raise_server_exceptions=False)
    for method, path in (("get", "/api/models"), ("get", "/api/portfolio/config")):
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Basic"

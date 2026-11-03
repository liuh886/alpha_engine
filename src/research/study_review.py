"""Continuous investment hypothesis review and learning loop (E1).

Formalizes the continuous scientific inquiry lifecycle:
1. Hypothesis formulation (提出假设): Economic rationale, expected alpha, falsification criteria.
2. Freeze conditions (冻结条件): Locked benchmark, universe, friction, and contract SHA-256.
3. Out-of-sample tracking (样本外观察): Tracking performance post-cutoff vs baselines.
4. Counter-evidence collection (收集反证): Recording falsifying episodes, beta drag, drawdown breaches.
5. Formulate conclusion (形成结论): State machine transitions with immutable justification.
6. Scheduled review (安排复核): Scheduled review sessions and automated breach triggers.

Strictly reuses existing Racetrack and Study Workspace contracts; zero second database.
All outputs are research_only=True and trade_ready=False.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReviewLifecycleState(str, enum.Enum):
    """Lifecycle states of an investment hypothesis."""

    FORMULATED = "formulated"  # Hypothesis declared, baseline under evaluation
    OBSERVING = "observing"  # Frozen conditions, actively observing out-of-sample performance
    SUPPORTED = "supported"  # Evidence supports hypothesis within expected boundaries
    CHALLENGED = "challenged"  # Significant counter-evidence accumulated; under review
    REFUTED = "refuted"  # Hypothesis falsified by empirical evidence; retired
    GRADUATED = "graduated"  # Persistently validated; eligible for formal candidate consideration


class CounterEvidenceSeverity(str, enum.Enum):
    """Severity of observed counter-evidence."""

    INFO = "info"  # Expected trade-off (e.g. lagging during high-beta rally)
    WARNING = "warning"  # Metrics deviation near falsification boundary
    FALSIFYING = "falsifying"  # Directly breaches declared falsification criteria


@dataclass(frozen=True)
class HypothesisSpec:
    """Specification of the core economic hypothesis."""

    statement: str
    economic_rationale: str
    expected_edge: str
    falsification_criteria: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "economic_rationale": self.economic_rationale,
            "expected_edge": self.expected_edge,
            "falsification_criteria": list(self.falsification_criteria),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HypothesisSpec:
        return cls(
            statement=str(data.get("statement", "")).strip(),
            economic_rationale=str(data.get("economic_rationale", "")).strip(),
            expected_edge=str(data.get("expected_edge", "")).strip(),
            falsification_criteria=[str(c).strip() for c in data.get("falsification_criteria", [])],
        )


@dataclass(frozen=True)
class FrozenConditions:
    """Frozen evaluation conditions for fair out-of-sample comparison."""

    frozen_at_cutoff: str  # ISO date string (e.g. '2024-01-01' or '2026-10-30')
    market: str  # 'us' or 'cn'
    pool_id: str  # e.g. 'us_selected_equities_v2'
    runner_id: str  # e.g. 'us87_low_vol_challenger_v1'
    benchmarks: list[str]  # e.g. ['us87_ew_pool_runner_v1', 'QQQ']
    cost_bps: float = 8.0  # e.g. 8.0
    rebalance_cadence: str = "monthly_first_session"  # e.g. 'monthly_first_session'
    contract_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "frozen_at_cutoff": self.frozen_at_cutoff,
            "market": self.market,
            "pool_id": self.pool_id,
            "runner_id": self.runner_id,
            "benchmarks": list(self.benchmarks),
            "cost_bps": self.cost_bps,
            "rebalance_cadence": self.rebalance_cadence,
            "contract_sha256": self.contract_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrozenConditions:
        return cls(
            frozen_at_cutoff=str(data.get("frozen_at_cutoff", "")).strip(),
            market=str(data.get("market", "")).strip(),
            pool_id=str(data.get("pool_id", "")).strip(),
            runner_id=str(data.get("runner_id", "")).strip(),
            benchmarks=[str(b).strip() for b in data.get("benchmarks", [])],
            cost_bps=float(data.get("cost_bps", 8.0)),
            rebalance_cadence=str(data.get("rebalance_cadence", "monthly_first_session")).strip(),
            contract_sha256=str(data.get("contract_sha256", "")).strip(),
        )


@dataclass(frozen=True)
class ObservationMetrics:
    """Quantitative performance snapshot under frozen conditions."""

    as_of_session: str
    sample_kind: str  # 'in_sample', 'out_of_sample', 'full_sample'
    cumulative_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    persistence_score: float
    vs_benchmark_returns: dict[str, float] = field(default_factory=dict)
    rebalances_count: int = 0
    cash_drag_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_session": self.as_of_session,
            "sample_kind": self.sample_kind,
            "cumulative_return": self.cumulative_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "persistence_score": self.persistence_score,
            "vs_benchmark_returns": dict(self.vs_benchmark_returns),
            "rebalances_count": self.rebalances_count,
            "cash_drag_ratio": self.cash_drag_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObservationMetrics:
        return cls(
            as_of_session=str(data.get("as_of_session", "")).strip(),
            sample_kind=str(data.get("sample_kind", "out_of_sample")).strip(),
            cumulative_return=float(data.get("cumulative_return", 0.0)),
            annualized_return=float(data.get("annualized_return", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            max_drawdown=float(data.get("max_drawdown", 0.0)),
            persistence_score=float(data.get("persistence_score", 0.0)),
            vs_benchmark_returns={
                str(k): float(v) for k, v in data.get("vs_benchmark_returns", {}).items()
            },
            rebalances_count=int(data.get("rebalances_count", 0)),
            cash_drag_ratio=float(data.get("cash_drag_ratio", 0.0)),
        )


@dataclass(frozen=True)
class CounterEvidenceItem:
    """An empirical observation challenging the hypothesis."""

    evidence_id: str
    session: str
    category: str  # 'beta_drag', 'drawdown_breach', 'liquidity_drag', 'turnover_drag', 'regime_inversion'
    severity: CounterEvidenceSeverity
    observation: str
    metrics_impact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "session": self.session,
            "category": self.category,
            "severity": self.severity.value,
            "observation": self.observation,
            "metrics_impact": dict(self.metrics_impact),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CounterEvidenceItem:
        sev_raw = str(data.get("severity", "info")).lower()
        try:
            sev = CounterEvidenceSeverity(sev_raw)
        except ValueError:
            sev = CounterEvidenceSeverity.INFO
        return cls(
            evidence_id=str(data.get("evidence_id", "")).strip(),
            session=str(data.get("session", "")).strip(),
            category=str(data.get("category", "")).strip(),
            severity=sev,
            observation=str(data.get("observation", "")).strip(),
            metrics_impact=dict(data.get("metrics_impact", {})),
        )


@dataclass(frozen=True)
class ReviewConclusion:
    """Current scientific verdict on the hypothesis."""

    verdict: str
    verdict_session: str
    summary: str
    supported_points: list[str]
    unresolved_risks: list[str]
    recommendation: str  # 'continue_observing', 'adjust_parameters', 'retire_hypothesis', 'promote_to_candidate'

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_session": self.verdict_session,
            "summary": self.summary,
            "supported_points": list(self.supported_points),
            "unresolved_risks": list(self.unresolved_risks),
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewConclusion:
        return cls(
            verdict=str(data.get("verdict", "")).strip(),
            verdict_session=str(data.get("verdict_session", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            supported_points=[str(p).strip() for p in data.get("supported_points", [])],
            unresolved_risks=[str(r).strip() for r in data.get("unresolved_risks", [])],
            recommendation=str(data.get("recommendation", "continue_observing")).strip(),
        )


@dataclass(frozen=True)
class ScheduledReview:
    """Scheduled review checkpoint and automatic alert triggers."""

    next_review_session: str  # ISO date (e.g. '2026-12-01')
    cadence: str  # 'monthly', 'quarterly', 'event_triggered'
    review_triggers: list[str]  # e.g. ['max_drawdown_below_-0.25', 'excess_return_3m_below_-0.15']

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_review_session": self.next_review_session,
            "cadence": self.cadence,
            "review_triggers": list(self.review_triggers),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduledReview:
        return cls(
            next_review_session=str(data.get("next_review_session", "")).strip(),
            cadence=str(data.get("cadence", "monthly")).strip(),
            review_triggers=[str(t).strip() for t in data.get("review_triggers", [])],
        )


@dataclass
class StudyReviewRecord:
    """Complete continuous review record for an investment hypothesis."""

    review_id: str
    title: str
    lifecycle_state: ReviewLifecycleState
    created_at: str
    updated_at: str
    hypothesis: HypothesisSpec
    frozen_conditions: FrozenConditions
    observations: dict[str, ObservationMetrics]
    counter_evidence: list[CounterEvidenceItem]
    conclusion: ReviewConclusion
    scheduled_review: ScheduledReview
    lineage_fingerprint: str = ""
    research_only: bool = True
    trade_ready: bool = False

    def __post_init__(self) -> None:
        if not self.lineage_fingerprint:
            self.lineage_fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint binding hypothesis and frozen conditions."""
        payload = {
            "review_id": self.review_id,
            "hypothesis": self.hypothesis.to_dict(),
            "frozen_conditions": self.frozen_conditions.to_dict(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "review_id": self.review_id,
            "title": self.title,
            "lifecycle_state": self.lifecycle_state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "hypothesis": self.hypothesis.to_dict(),
            "frozen_conditions": self.frozen_conditions.to_dict(),
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
            "counter_evidence": [e.to_dict() for e in self.counter_evidence],
            "conclusion": self.conclusion.to_dict(),
            "scheduled_review": self.scheduled_review.to_dict(),
            "lineage_fingerprint": self.lineage_fingerprint,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudyReviewRecord:
        state_raw = str(data.get("lifecycle_state", "formulated")).lower()
        try:
            state = ReviewLifecycleState(state_raw)
        except ValueError:
            state = ReviewLifecycleState.FORMULATED

        observations = {
            k: ObservationMetrics.from_dict(v)
            for k, v in data.get("observations", {}).items()
            if isinstance(v, dict)
        }
        counter_evidence = [
            CounterEvidenceItem.from_dict(e)
            for e in data.get("counter_evidence", [])
            if isinstance(e, dict)
        ]

        return cls(
            review_id=str(data.get("review_id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            lifecycle_state=state,
            created_at=str(data.get("created_at", "")).strip(),
            updated_at=str(data.get("updated_at", "")).strip(),
            hypothesis=HypothesisSpec.from_dict(data.get("hypothesis", {})),
            frozen_conditions=FrozenConditions.from_dict(data.get("frozen_conditions", {})),
            observations=observations,
            counter_evidence=counter_evidence,
            conclusion=ReviewConclusion.from_dict(data.get("conclusion", {})),
            scheduled_review=ScheduledReview.from_dict(data.get("scheduled_review", {})),
            lineage_fingerprint=str(data.get("lineage_fingerprint", "")).strip(),
            research_only=bool(data.get("research_only", True)),
            trade_ready=bool(data.get("trade_ready", False)),
        )


def create_study_review(
    review_id: str,
    title: str,
    hypothesis: HypothesisSpec,
    frozen_conditions: FrozenConditions,
    scheduled_review: ScheduledReview,
    initial_observations: dict[str, ObservationMetrics] | None = None,
    initial_counter_evidence: list[CounterEvidenceItem] | None = None,
    initial_conclusion: ReviewConclusion | None = None,
    lifecycle_state: ReviewLifecycleState = ReviewLifecycleState.OBSERVING,
) -> StudyReviewRecord:
    """Create a new StudyReviewRecord with timestamp and cryptographic fingerprint."""
    now = datetime.now(timezone.utc).isoformat()
    if initial_conclusion is None:
        initial_conclusion = ReviewConclusion(
            verdict="Hypothesis frozen; awaiting ongoing out-of-sample observation",
            verdict_session=frozen_conditions.frozen_at_cutoff,
            summary="Conditions locked under Racetrack Q/NAV engine. Review scheduled.",
            supported_points=[],
            unresolved_risks=[],
            recommendation="continue_observing",
        )

    return StudyReviewRecord(
        review_id=review_id,
        title=title,
        lifecycle_state=lifecycle_state,
        created_at=now,
        updated_at=now,
        hypothesis=hypothesis,
        frozen_conditions=frozen_conditions,
        observations=dict(initial_observations or {}),
        counter_evidence=list(initial_counter_evidence or []),
        conclusion=initial_conclusion,
        scheduled_review=scheduled_review,
        research_only=True,
        trade_ready=False,
    )


def save_study_review(record: StudyReviewRecord, path: Path | str) -> Path:
    """Save study review record to a formatted JSON file."""
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_study_review(path: Path | str) -> StudyReviewRecord:
    """Load study review record from JSON file with validation."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Study review file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    record = StudyReviewRecord.from_dict(data)
    # Check fingerprint integrity
    expected = record.compute_fingerprint()
    if record.lineage_fingerprint and record.lineage_fingerprint != expected:
        raise ValueError(
            f"Review record fingerprint mismatch: expected {expected}, got {record.lineage_fingerprint}"
        )
    return record


def add_counter_evidence(
    record: StudyReviewRecord,
    category: str,
    observation: str,
    session: str,
    severity: CounterEvidenceSeverity = CounterEvidenceSeverity.WARNING,
    metrics_impact: dict[str, Any] | None = None,
) -> StudyReviewRecord:
    """Append a counter-evidence item and evaluate state transitions."""
    evidence_id = f"CE-{len(record.counter_evidence) + 1:03d}"
    item = CounterEvidenceItem(
        evidence_id=evidence_id,
        session=session,
        category=category,
        severity=severity,
        observation=observation,
        metrics_impact=metrics_impact or {},
    )
    record.counter_evidence.append(item)
    record.updated_at = datetime.now(timezone.utc).isoformat()

    # Automatic state transition if severe counter-evidence
    if severity == CounterEvidenceSeverity.FALSIFYING:
        record.lifecycle_state = ReviewLifecycleState.CHALLENGED
    elif severity == CounterEvidenceSeverity.WARNING and record.lifecycle_state in (
        ReviewLifecycleState.SUPPORTED,
        ReviewLifecycleState.OBSERVING,
    ):
        record.lifecycle_state = ReviewLifecycleState.CHALLENGED

    return record


def format_study_review_markdown(record: StudyReviewRecord) -> str:
    """Render a human-friendly GitHub Flavored Markdown review report."""
    state_icons = {
        ReviewLifecycleState.FORMULATED: "📝 FORMULATED",
        ReviewLifecycleState.OBSERVING: "🔭 OBSERVING",
        ReviewLifecycleState.SUPPORTED: "🟢 SUPPORTED",
        ReviewLifecycleState.CHALLENGED: "⚠️ CHALLENGED",
        ReviewLifecycleState.REFUTED: "❌ REFUTED",
        ReviewLifecycleState.GRADUATED: "🎓 GRADUATED",
    }
    badge = state_icons.get(record.lifecycle_state, record.lifecycle_state.value.upper())

    lines = [
        f"# Investment Hypothesis Continuous Review: {record.title}",
        "",
        f"- **Review ID**: `{record.review_id}`",
        f"- **Lifecycle State**: **{badge}**",
        f"- **Created At**: `{record.created_at}`",
        f"- **Last Updated**: `{record.updated_at}`",
        f"- **Lineage Fingerprint**: `{record.lineage_fingerprint[:16]}...`",
        f"- **Research Only**: `{record.research_only}` (Trade Ready: `{record.trade_ready}`)",
        "",
        "---",
        "",
        "## 1. Hypothesis Formulation (提出假设)",
        "",
        f"> **Core Thesis**: {record.hypothesis.statement}",
        "",
        f"- **Economic Rationale**: {record.hypothesis.economic_rationale}",
        f"- **Expected Edge**: {record.hypothesis.expected_edge}",
        "- **Falsification Criteria (证伪门槛)**:",
    ]
    for crit in record.hypothesis.falsification_criteria:
        lines.append(f"  - 🔴 {crit}")
    lines.append("")

    lines.extend([
        "## 2. Frozen Conditions (冻结条件)",
        "",
        f"- **Frozen Cutoff**: `{record.frozen_conditions.frozen_at_cutoff}`",
        f"- **Market / Pool**: `{record.frozen_conditions.market.upper()}` / `{record.frozen_conditions.pool_id}`",
        f"- **Runner ID**: `{record.frozen_conditions.runner_id}`",
        f"- **Benchmarks**: {', '.join(f'`{b}`' for b in record.frozen_conditions.benchmarks)}",
        f"- **Friction Model**: `{record.frozen_conditions.cost_bps} bps` (One-sided default)",
        f"- **Rebalance Cadence**: `{record.frozen_conditions.rebalance_cadence}`",
        "",
    ])

    lines.extend([
        "## 3. Performance Observations (表现观察)",
        "",
        "| Observation Scope | Cumulative Return | Annualized | Sharpe | Max Drawdown | vs Pool EW | vs QQQ | Rebalances |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for scope_key, metrics in record.observations.items():
        vs_ew = metrics.vs_benchmark_returns.get("us87_ew_pool_runner_v1")
        vs_qqq = metrics.vs_benchmark_returns.get("QQQ")
        ew_str = f"{vs_ew * 100:+.1f}%" if vs_ew is not None else "n/a"
        qqq_str = f"{vs_qqq * 100:+.1f}%" if vs_qqq is not None else "n/a"
        lines.append(
            f"| `{scope_key}` ({metrics.as_of_session}) | {metrics.cumulative_return * 100:+.1f}% | "
            f"{metrics.annualized_return * 100:+.1f}% | {metrics.sharpe_ratio:.2f} | "
            f"{metrics.max_drawdown * 100:.1f}% | {ew_str} | {qqq_str} | {metrics.rebalances_count} |"
        )
    lines.append("")

    lines.extend([
        "## 4. Counter-Evidence Collection (反证收集与证伪检验)",
        "",
    ])
    if not record.counter_evidence:
        lines.append("*No counter-evidence observed to date.*")
    else:
        lines.extend([
            "| ID | Session | Category | Severity | Observed Episode / Evidence |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for ce in record.counter_evidence:
            sev_badge = "🔴 FALSIFYING" if ce.severity == CounterEvidenceSeverity.FALSIFYING else (
                "🟡 WARNING" if ce.severity == CounterEvidenceSeverity.WARNING else "⚪ INFO"
            )
            lines.append(f"| `{ce.evidence_id}` | `{ce.session}` | `{ce.category}` | {sev_badge} | {ce.observation} |")
    lines.append("")

    lines.extend([
        "## 5. Review Conclusion (当前结论)",
        "",
        f"- **Verdict**: **{record.conclusion.verdict}**",
        f"- **Verdict Session**: `{record.conclusion.verdict_session}`",
        f"- **Summary**: {record.conclusion.summary}",
        f"- **Recommendation**: `{record.conclusion.recommendation}`",
    ])
    if record.conclusion.supported_points:
        lines.append("- **Supported Empirical Evidence**:")
        for sp in record.conclusion.supported_points:
            lines.append(f"  - ✅ {sp}")
    if record.conclusion.unresolved_risks:
        lines.append("- **Unresolved Risks & Caveats**:")
        for ur in record.conclusion.unresolved_risks:
            lines.append(f"  - ⚠️ {ur}")
    lines.append("")

    lines.extend([
        "## 6. Scheduled Review & Watchpoints (后续复核与触发预警)",
        "",
        f"- **Next Review Session**: `{record.scheduled_review.next_review_session}`",
        f"- **Review Cadence**: `{record.scheduled_review.cadence}`",
        "- **Automated Breach Triggers**:",
    ])
    for trigger in record.scheduled_review.review_triggers:
        lines.append(f"  - ⚡ `{trigger}`")
    lines.append("")

    return "\n".join(lines)


def list_study_reviews(directory: Path | str) -> list[dict[str, Any]]:
    """Scan and list summary metadata of all study reviews in a directory."""
    d = Path(directory).resolve()
    if not d.is_dir():
        return []
    summaries = []
    for file in sorted(d.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if data.get("schema_version") == "1.0" and "review_id" in data:
                summaries.append({
                    "review_id": data["review_id"],
                    "title": data.get("title", ""),
                    "lifecycle_state": data.get("lifecycle_state", "formulated"),
                    "runner_id": data.get("frozen_conditions", {}).get("runner_id", ""),
                    "market": data.get("frozen_conditions", {}).get("market", ""),
                    "next_review_session": data.get("scheduled_review", {}).get("next_review_session", ""),
                    "counter_evidence_count": len(data.get("counter_evidence", [])),
                    "path": str(file),
                })
        except Exception:
            continue
    return summaries

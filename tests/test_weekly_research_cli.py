"""Tests for weekly_research CLI argument handling and report generation.

These tests verify market selection, skip flags, and report field correctness
without requiring real data or Qlib infrastructure.
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.generate_weekly_report import build_weekly_report
from src.research.promotion_decision import PromotionStatus
from src.research.workflow_types import (
    ResearchStep,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
    StepResult,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    market: str,
    status: WorkflowStatus = WorkflowStatus.COMPLETED,
    promote_status: str = PromotionStatus.TRADE_GUIDANCE_CANDIDATE.value,
    trade_ready: bool = True,
) -> ResearchWorkflowResult:
    """Build a canned ``ResearchWorkflowResult`` for testing."""
    return ResearchWorkflowResult(
        run_id=f"test-{market}-001",
        request=ResearchWorkflowRequest(market=market, goal=f"test {market}"),
        status=status,
        steps=[
            StepResult(step=ResearchStep.SCAN, status=WorkflowStatus.COMPLETED),
            StepResult(step=ResearchStep.COMPILE, status=WorkflowStatus.COMPLETED),
            StepResult(step=ResearchStep.PROMOTE, status=WorkflowStatus.COMPLETED),
        ],
        started_at="2026-07-18T00:00:00Z",
        completed_at="2026-07-18T01:00:00Z",
        promotion_decision={"status": promote_status, "trade_ready": trade_ready},
    )


# ---------------------------------------------------------------------------
# Market selection via main() → run_weekly_research()
# ---------------------------------------------------------------------------


class TestMarketSelection:
    """--market us / cn / all restricts execution to selected markets."""

    @patch("scripts.weekly_research.run_weekly_research")
    def test_market_us(self, mock_run):
        """--market us runs only US."""
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py", "--market", "us"]):
            main()

        mock_run.assert_called_once_with(
            markets=["us"], skip_data=False, skip_decay=False,
        )

    @patch("scripts.weekly_research.run_weekly_research")
    def test_market_cn(self, mock_run):
        """--market cn runs only CN."""
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py", "--market", "cn"]):
            main()

        mock_run.assert_called_once_with(
            markets=["cn"], skip_data=False, skip_decay=False,
        )

    @patch("scripts.weekly_research.run_weekly_research")
    def test_market_all_default(self, mock_run):
        """Default (no market flag) runs both US and CN."""
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py"]):
            main()

        mock_run.assert_called_once_with(
            markets=["us", "cn"], skip_data=False, skip_decay=False,
        )

    @patch("scripts.weekly_research.run_weekly_research")
    def test_market_all_explicit(self, mock_run):
        """--market all runs both US and CN."""
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py", "--market", "all"]):
            main()

        mock_run.assert_called_once_with(
            markets=["us", "cn"], skip_data=False, skip_decay=False,
        )


# ---------------------------------------------------------------------------
# Skip flags
# ---------------------------------------------------------------------------


class TestSkipFlags:
    """--skip-data and --skip-decay are plumbed correctly."""

    @patch("scripts.weekly_research.run_weekly_research")
    def test_skip_data(self, mock_run):
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py", "--skip-data"]):
            main()

        mock_run.assert_called_once_with(
            markets=["us", "cn"], skip_data=True, skip_decay=False,
        )

    @patch("scripts.weekly_research.run_weekly_research")
    def test_skip_decay(self, mock_run):
        from scripts.weekly_research import main

        with patch("sys.argv", ["weekly_research.py", "--skip-decay"]):
            main()

        mock_run.assert_called_once_with(
            markets=["us", "cn"], skip_data=False, skip_decay=True,
        )

    @patch("scripts.weekly_research.run_weekly_research")
    def test_skip_both_with_market(self, mock_run):
        """All flags compose correctly."""
        from scripts.weekly_research import main

        with patch("sys.argv", [
            "weekly_research.py", "--skip-data", "--skip-decay", "--market", "us",
        ]):
            main()

        mock_run.assert_called_once_with(
            markets=["us"], skip_data=True, skip_decay=True,
        )


# ---------------------------------------------------------------------------
# run_weekly_research — market and skip flag internal behavior
# ---------------------------------------------------------------------------


class TestRunWeeklyResearch:
    """Integration of run_weekly_research with mocked internals."""

    def test_market_us_skips_cn(self):
        """With markets=["us"], CN refresh and research are never called."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]) as mock_decay,
            patch("scripts.weekly_research._run_research_for_market", return_value=_make_result("us")) as mock_research,
            patch("scripts.weekly_research._refresh_market_data", return_value=True) as mock_refresh,
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us"])

        assert code == 0
        mock_refresh.assert_called_once_with("us")
        mock_research.assert_called_once_with("us")
        mock_decay.assert_called_once()

    def test_market_cn_skips_us(self):
        """With markets=["cn"], US refresh and research are never called."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]) as mock_decay,
            patch("scripts.weekly_research._run_research_for_market", return_value=_make_result("cn")) as mock_research,
            patch("scripts.weekly_research._refresh_market_data", return_value=True) as mock_refresh,
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["cn"])

        assert code == 0
        mock_refresh.assert_called_once_with("cn")
        mock_research.assert_called_once_with("cn")
        mock_decay.assert_called_once()

    def test_skip_data_skips_refresh(self):
        """With skip_data=True, _refresh_market_data is never called."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]) as mock_decay,
            patch("scripts.weekly_research._run_research_for_market", return_value=_make_result("us")) as mock_research,
            patch("scripts.weekly_research._refresh_market_data", return_value=True) as mock_refresh,
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us", "cn"], skip_data=True)

        assert code == 0
        mock_refresh.assert_not_called()
        # Research still runs for both markets
        assert mock_research.call_count == 2
        mock_decay.assert_called_once()

    def test_skip_decay_skips_decay_check(self):
        """With skip_decay=True, _check_factor_decay is never called."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay") as mock_decay,
            patch("scripts.weekly_research._run_research_for_market", return_value=_make_result("us")),
            patch("scripts.weekly_research._refresh_market_data", return_value=True),
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us"], skip_decay=True)

        assert code == 0
        mock_decay.assert_not_called()

    def test_data_refresh_failure_skips_research(self):
        """When data refresh fails for a market, its research is skipped."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]),
            patch("scripts.weekly_research._run_research_for_market") as mock_research,
            patch(
                "scripts.weekly_research._refresh_market_data",
                side_effect=lambda m: m == "cn",  # us fails, cn succeeds
            ) as mock_refresh,
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us", "cn"])

        assert code == 1  # partial failure
        mock_refresh.assert_any_call("us")
        mock_refresh.assert_any_call("cn")
        # Only CN research runs (US refresh failed)
        mock_research.assert_called_once_with("cn")

    def test_report_still_generated_after_failure(self):
        """Report and journal logging execute even after failures."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report") as mock_save,
            patch("scripts.weekly_research._log_to_journal") as mock_log,
            patch("scripts.weekly_research._check_factor_decay", return_value=[]),
            patch("scripts.weekly_research._run_research_for_market"),
            patch("scripts.weekly_research._refresh_market_data", return_value=False),
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us", "cn"])

        assert code == 1  # partial failure
        mock_save.assert_called_once()
        mock_log.assert_called_once()

    def test_research_failed_status_results_in_error(self):
        """Research result with FAILED status adds error and returns code 1."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]),
            patch(
                "scripts.weekly_research._run_research_for_market",
                return_value=_make_result("us", status=WorkflowStatus.FAILED),
            ),
            patch("scripts.weekly_research._refresh_market_data", return_value=True),
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us"])

        assert code == 1  # partial failure due to FAILED workflow status

    def test_research_skipped_status_results_in_error(self):
        """Research result with SKIPPED status adds error and returns code 1."""
        with (
            patch("src.governance.service.GovernanceService"),
            patch("scripts.weekly_research._save_report"),
            patch("scripts.weekly_research._log_to_journal"),
            patch("scripts.weekly_research._check_factor_decay", return_value=[]),
            patch(
                "scripts.weekly_research._run_research_for_market",
                return_value=_make_result("us", status=WorkflowStatus.SKIPPED),
            ),
            patch("scripts.weekly_research._refresh_market_data", return_value=True),
        ):
            from scripts.weekly_research import run_weekly_research

            code = run_weekly_research(markets=["us"])

        assert code == 1  # partial failure due to SKIPPED workflow status


# ---------------------------------------------------------------------------
# Report generation — truthful field presence
# ---------------------------------------------------------------------------


class TestWeeklyReportFields:
    """Canonical report contains correct fields per market state."""

    def test_both_markets_present(self):
        """Report includes both US and CN sections when both have results."""
        us = _make_result("us")
        cn = _make_result("cn")
        report = build_weekly_report(
            us_result=us,
            cn_result=cn,
            decay_results=[],
            market_success={"us": True, "cn": True},
        )
        assert "**US**" in report
        assert "**CN**" in report
        assert "test-us-001" in report
        assert "test-cn-001" in report
        assert "Markets executed: **US + CN**" in report

    def test_only_us_market(self):
        """Report omits CN section when CN was not run."""
        us = _make_result("us")
        report = build_weekly_report(
            us_result=us,
            cn_result=None,
            decay_results=[],
            market_success={"us": True},
        )
        assert "**US**" in report
        assert "**CN**" not in report
        assert "Markets executed: **US**" in report

    def test_only_cn_market(self):
        """Report omits US section when US was not run."""
        cn = _make_result("cn")
        report = build_weekly_report(
            us_result=None,
            cn_result=cn,
            decay_results=[],
            market_success={"cn": True},
        )
        assert "**CN**" in report
        assert "**US**" not in report
        assert "Markets executed: **CN**" in report

    def test_unselected_market_not_failed(self):
        """Missing markets are absent, not flagged as failures."""
        report = build_weekly_report(
            us_result=None,
            cn_result=None,
            decay_results=[],
            market_success={},
        )
        assert "Markets executed: **none**" in report
        # Absent markets are not failures
        assert "No research run this week" in report

    def test_decay_alerts_in_report(self):
        """Decay results appear in the report."""
        decay = [
            {
                "name": "TEST_FACTOR",
                "status": "decaying",
                "recent_ic": 0.01,
                "historical_ic": 0.05,
                "decay_ratio": 0.8,
            },
        ]
        report = build_weekly_report(
            us_result=_make_result("us"),
            cn_result=_make_result("cn"),
            decay_results=decay,
            market_success={"us": True, "cn": True},
        )
        assert "1 factor(s) showing alpha decay" in report
        assert "TEST_FACTOR" in report

    def test_all_section_headers_present(self):
        """Report contains all expected section headers."""
        report = build_weekly_report(
            us_result=_make_result("us"),
            cn_result=_make_result("cn"),
            decay_results=[],
            market_success={"us": True, "cn": True},
        )
        for section in [
            "Executive Summary",
            "Research Cycles",
            "Factor Library Status",
            "Top Performers",
            "Decay Alerts",
            "Walk-Forward Validation",
            "Recommendations",
        ]:
            assert section in report, f"Missing section: {section}"

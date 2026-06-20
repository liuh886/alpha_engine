"""Portfolio Constraint Engine — Multi-dimensional portfolio risk constraints.

This module provides portfolio-level constraints beyond simple position limits:
- Industry concentration limits
- Correlation crowding detection
- Single-factor exposure caps
- Liquidity capacity constraints
- Turnover cost management
- Consecutive loss de-leverage

Usage:
    engine = PortfolioConstraintEngine(config)
    violations = engine.check_portfolio(portfolio, market_data)
    adjusted = engine.apply_constraints(portfolio, violations)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

__all__ = [
    "ConstraintType",
    "ConstraintViolation",
    "PortfolioConstraintEngine",
    "DEFAULT_CONSTRAINT_CONFIG",
]


class ConstraintType(str, Enum):
    """Types of portfolio constraints."""
    INDUSTRY_CONCENTRATION = "industry_concentration"
    CORRELATION_CROWDING = "correlation_crowding"
    FACTOR_EXPOSURE = "factor_exposure"
    LIQUIDITY_CAPACITY = "liquidity_capacity"
    TURNOVER_COST = "turnover_cost"
    CONSECUTIVE_LOSS = "consecutive_loss"


@dataclass
class ConstraintViolation:
    """A single constraint violation.

    Attributes
    ----------
    type : ConstraintType
        Type of constraint violated.
    severity : str
        "warning" or "critical".
    message : str
        Human-readable description.
    details : dict
        Additional details about the violation.
    suggested_action : str
        Recommended action to resolve.
    """

    type: ConstraintType
    severity: str = "warning"
    message: str = ""
    details: dict = field(default_factory=dict)
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "suggested_action": self.suggested_action,
        }


# Default constraint configuration
DEFAULT_CONSTRAINT_CONFIG: dict[str, Any] = {
    # Industry concentration
    "max_industry_weight": 0.30,        # Max 30% in any single industry
    "max_top3_industry_weight": 0.60,   # Max 60% in top 3 industries

    # Correlation crowding
    "max_pairwise_correlation": 0.80,   # Max correlation between any two positions
    "max_avg_correlation": 0.50,        # Max average pairwise correlation
    "correlation_lookback_days": 60,    # Days for correlation calculation

    # Factor exposure
    "max_single_factor_exposure": 2.0,  # Max z-score for any single factor
    "max_factor_exposure_abs": 1.5,     # Max absolute factor exposure

    # Liquidity capacity
    "min_daily_volume_usd": 1_000_000,  # Min daily volume in USD
    "max_position_pct_adv": 0.05,       # Max 5% of average daily volume

    # Turnover cost
    "max_daily_turnover": 0.20,         # Max 20% daily turnover
    "max_monthly_turnover": 1.00,       # Max 100% monthly turnover
    "turnover_cost_bps": 10,            # Estimated cost per turnover in bps

    # Consecutive loss de-leverage
    "consecutive_loss_days": 5,         # Days of consecutive losses
    "deleverage_factor": 0.50,          # Reduce exposure by 50%
    "loss_threshold_pct": -0.02,        # Daily loss threshold
}


@dataclass
class PortfolioConstraintEngine:
    """Portfolio-level constraint engine.

    Attributes
    ----------
    config : dict
        Constraint configuration (see DEFAULT_CONSTRAINT_CONFIG).
    """

    config: dict = field(default_factory=lambda: DEFAULT_CONSTRAINT_CONFIG.copy())

    def check_portfolio(
        self,
        positions: dict[str, float],  # symbol -> weight
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check portfolio against all constraints.

        Parameters
        ----------
        positions : dict[str, float]
            Portfolio positions {symbol: weight}.
        market_data : dict[str, Any]
            Market data including:
            - industry_map: {symbol: industry}
            - returns_df: DataFrame of historical returns
            - volume_df: DataFrame of daily volumes
            - factor_exposures: {symbol: {factor: z_score}}
            - daily_returns: list of recent daily returns

        Returns
        -------
        list[ConstraintViolation]
            List of violations found.
        """
        violations = []

        # Check each constraint type
        violations.extend(self._check_industry_concentration(positions, market_data))
        violations.extend(self._check_correlation_crowding(positions, market_data))
        violations.extend(self._check_factor_exposure(positions, market_data))
        violations.extend(self._check_liquidity_capacity(positions, market_data))
        violations.extend(self._check_turnover_cost(positions, market_data))
        violations.extend(self._check_consecutive_loss(market_data))

        return violations

    def _check_industry_concentration(
        self,
        positions: dict[str, float],
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check industry concentration limits."""
        violations = []
        industry_map = market_data.get("industry_map", {})

        if not industry_map:
            return violations

        # Calculate industry weights
        industry_weights: dict[str, float] = {}
        for symbol, weight in positions.items():
            industry = industry_map.get(symbol, "Unknown")
            industry_weights[industry] = industry_weights.get(industry, 0) + weight

        # Check single industry limit
        max_weight = self.config["max_industry_weight"]
        for industry, weight in industry_weights.items():
            if weight > max_weight:
                violations.append(ConstraintViolation(
                    type=ConstraintType.INDUSTRY_CONCENTRATION,
                    severity="critical" if weight > max_weight * 1.2 else "warning",
                    message=f"Industry '{industry}' weight {weight:.1%} exceeds limit {max_weight:.1%}",
                    details={"industry": industry, "weight": weight, "limit": max_weight},
                    suggested_action=f"Reduce {industry} exposure by {weight - max_weight:.1%}",
                ))

        # Check top-3 industry concentration
        sorted_industries = sorted(industry_weights.values(), reverse=True)
        top3_weight = sum(sorted_industries[:3])
        max_top3 = self.config["max_top3_industry_weight"]
        if top3_weight > max_top3:
            violations.append(ConstraintViolation(
                type=ConstraintType.INDUSTRY_CONCENTRATION,
                severity="warning",
                message=f"Top 3 industries weight {top3_weight:.1%} exceeds limit {max_top3:.1%}",
                details={"top3_weight": top3_weight, "limit": max_top3},
                suggested_action="Diversify across more industries",
            ))

        return violations

    def _check_correlation_crowding(
        self,
        positions: dict[str, float],
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check correlation crowding."""
        violations = []
        returns_df = market_data.get("returns_df")

        if returns_df is None or returns_df.empty:
            return violations

        symbols = list(positions.keys())
        available = [s for s in symbols if s in returns_df.columns]

        if len(available) < 2:
            return violations

        # Calculate pairwise correlations
        corr_matrix = returns_df[available].corr()
        max_corr = self.config["max_pairwise_correlation"]
        avg_corr = self.config["max_avg_correlation"]

        # Check pairwise
        for i, s1 in enumerate(available):
            for s2 in available[i+1:]:
                corr = corr_matrix.loc[s1, s2]
                if abs(corr) > max_corr:
                    violations.append(ConstraintViolation(
                        type=ConstraintType.CORRELATION_CROWDING,
                        severity="warning",
                        message=f"High correlation ({corr:.2f}) between {s1} and {s2}",
                        details={"symbol1": s1, "symbol2": s2, "correlation": corr},
                        suggested_action=f"Consider reducing one of {s1}/{s2}",
                    ))

        # Check average correlation
        n = len(available)
        if n > 1:
            mask = np.triu(np.ones((n, n), dtype=bool), k=1)
            avg = corr_matrix.values[mask].mean()
            if avg > avg_corr:
                violations.append(ConstraintViolation(
                    type=ConstraintType.CORRELATION_CROWDING,
                    severity="warning",
                    message=f"Portfolio average correlation {avg:.2f} exceeds limit {avg_corr:.2f}",
                    details={"avg_correlation": avg, "limit": avg_corr},
                    suggested_action="Add uncorrelated positions to diversify",
                ))

        return violations

    def _check_factor_exposure(
        self,
        positions: dict[str, float],
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check single-factor exposure limits."""
        violations = []
        factor_exposures = market_data.get("factor_exposures", {})

        if not factor_exposures:
            return violations

        max_exp = self.config["max_single_factor_exposure"]

        # Calculate portfolio factor exposure
        for symbol, weight in positions.items():
            exposures = factor_exposures.get(symbol, {})
            for factor, z_score in exposures.items():
                weighted_exp = abs(weight * z_score)
                if weighted_exp > max_exp:
                    violations.append(ConstraintViolation(
                        type=ConstraintType.FACTOR_EXPOSURE,
                        severity="warning",
                        message=f"High {factor} exposure ({weighted_exp:.2f}) from {symbol}",
                        details={"symbol": symbol, "factor": factor, "exposure": weighted_exp},
                        suggested_action=f"Reduce {symbol} position or hedge {factor} exposure",
                    ))

        return violations

    def _check_liquidity_capacity(
        self,
        positions: dict[str, float],
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check liquidity capacity constraints.

        Uses price × volume (ADV in currency units) for capacity checks.
        Falls back to raw volume if price_df not available.
        """
        violations = []
        volume_df = market_data.get("volume_df")
        price_df = market_data.get("price_df")
        portfolio_value = market_data.get("portfolio_value", 100000)

        if volume_df is None or volume_df.empty:
            return violations

        min_adv = self.config["min_daily_volume_usd"]
        max_pct_adv = self.config["max_position_pct_adv"]

        for symbol, weight in positions.items():
            if symbol not in volume_df.columns:
                continue

            avg_volume_shares = volume_df[symbol].tail(20).mean()
            position_value = portfolio_value * weight

            # Compute ADV in currency: price × volume
            if price_df is not None and symbol in price_df.columns:
                avg_price = price_df[symbol].tail(20).mean()
                adv_currency = avg_price * avg_volume_shares
            else:
                # Fallback: assume volume is already in currency units
                adv_currency = avg_volume_shares

            # Check minimum ADV (in currency)
            if adv_currency < min_adv:
                violations.append(ConstraintViolation(
                    type=ConstraintType.LIQUIDITY_CAPACITY,
                    severity="warning",
                    message=f"{symbol} ADV {adv_currency:,.0f} below minimum {min_adv:,.0f}",
                    details={
                        "symbol": symbol,
                        "adv_currency": adv_currency,
                        "adv_shares": avg_volume_shares,
                        "min_adv": min_adv,
                    },
                    suggested_action=f"Reduce {symbol} position size",
                ))

            # Check position as % of ADV
            if adv_currency > 0:
                pct_adv = position_value / adv_currency
                if pct_adv > max_pct_adv:
                    violations.append(ConstraintViolation(
                        type=ConstraintType.LIQUIDITY_CAPACITY,
                        severity="critical" if pct_adv > max_pct_adv * 2 else "warning",
                        message=f"{symbol} position {pct_adv:.1%} of ADV ({adv_currency:,.0f}) exceeds {max_pct_adv:.1%}",
                        details={
                            "symbol": symbol,
                            "pct_adv": pct_adv,
                            "adv_currency": adv_currency,
                            "position_value": position_value,
                            "limit": max_pct_adv,
                        },
                        suggested_action=f"Reduce {symbol} to <{max_pct_adv:.1%} of ADV",
                    ))

        return violations

    def _check_turnover_cost(
        self,
        positions: dict[str, float],
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check turnover cost constraints."""
        violations = []
        prev_positions = market_data.get("prev_positions", {})

        if not prev_positions:
            return violations

        # Calculate turnover
        all_symbols = set(positions.keys()) | set(prev_positions.keys())
        total_turnover = 0
        for symbol in all_symbols:
            old_weight = prev_positions.get(symbol, 0)
            new_weight = positions.get(symbol, 0)
            total_turnover += abs(new_weight - old_weight)

        total_turnover /= 2  # One-way turnover

        max_daily = self.config["max_daily_turnover"]
        if total_turnover > max_daily:
            cost_bps = self.config["turnover_cost_bps"]
            cost_pct = total_turnover * cost_bps / 10000
            violations.append(ConstraintViolation(
                type=ConstraintType.TURNOVER_COST,
                severity="warning",
                message=f"Daily turnover {total_turnover:.1%} exceeds limit {max_daily:.1%} (cost: {cost_pct:.2%})",
                details={"turnover": total_turnover, "limit": max_daily, "cost_pct": cost_pct},
                suggested_action="Reduce turnover by keeping more positions",
            ))

        return violations

    def _check_consecutive_loss(
        self,
        market_data: dict[str, Any],
    ) -> list[ConstraintViolation]:
        """Check consecutive loss de-leverage."""
        violations = []
        daily_returns = market_data.get("daily_returns", [])

        if not daily_returns:
            return violations

        threshold = self.config["loss_threshold_pct"]
        consecutive_days = self.config["consecutive_loss_days"]

        # Count consecutive losses
        loss_streak = 0
        for ret in reversed(daily_returns):
            if ret < threshold:
                loss_streak += 1
            else:
                break

        if loss_streak >= consecutive_days:
            deleverage = self.config["deleverage_factor"]
            violations.append(ConstraintViolation(
                type=ConstraintType.CONSECUTIVE_LOSS,
                severity="critical",
                message=f"{loss_streak} consecutive loss days (>{consecutive_days} threshold)",
                details={"loss_streak": loss_streak, "threshold": consecutive_days, "deleverage_factor": deleverage},
                suggested_action=f"Reduce exposure by {deleverage:.0%}",
            ))

        return violations

    def apply_constraints(
        self,
        positions: dict[str, float],
        violations: list[ConstraintViolation],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Apply constraint adjustments to positions.

        Parameters
        ----------
        positions : dict[str, float]
            Original portfolio positions.
        violations : list[ConstraintViolation]
            Violations from check_portfolio().
        market_data : dict, optional
            Market data including industry_map for industry concentration fixes.

        Returns
        -------
        dict[str, float]
            Adjusted positions.
        """
        adjusted = dict(positions)
        industry_map = (market_data or {}).get("industry_map", {})

        for violation in violations:
            if violation.type == ConstraintType.INDUSTRY_CONCENTRATION:
                # Scale down industry positions proportionally
                industry = violation.details.get("industry")
                limit = violation.details.get("limit", self.config["max_industry_weight"])
                current = violation.details.get("weight", 0)
                if current > 0 and industry and industry_map:
                    scale = limit / current
                    for symbol, weight in adjusted.items():
                        if industry_map.get(symbol) == industry:
                            adjusted[symbol] = weight * scale
                    logger.info("industry_concentration_applied",
                                industry=industry, scale=scale)

            elif violation.type == ConstraintType.CONSECUTIVE_LOSS:
                # De-leverage all positions
                factor = violation.details.get("deleverage_factor", 0.5)
                adjusted = {s: w * factor for s, w in adjusted.items()}
                logger.info("deleverage_applied", factor=factor, reason=violation.message)

            elif violation.type == ConstraintType.LIQUIDITY_CAPACITY:
                # Reduce specific position
                symbol = violation.details.get("symbol")
                if symbol and symbol in adjusted:
                    limit = violation.details.get("limit", self.config["max_position_pct_adv"])
                    pct_adv = violation.details.get("pct_adv", 0)
                    if pct_adv > 0:
                        scale = limit / pct_adv
                        adjusted[symbol] *= scale
                        logger.info("liquidity_cap_applied", symbol=symbol, scale=scale)

        return adjusted

    def get_summary(self, violations: list[ConstraintViolation]) -> dict[str, Any]:
        """Get summary of constraint violations."""
        by_type = {}
        for v in violations:
            by_type.setdefault(v.type.value, []).append(v.to_dict())

        critical = sum(1 for v in violations if v.severity == "critical")
        warnings = sum(1 for v in violations if v.severity == "warning")

        return {
            "total_violations": len(violations),
            "critical": critical,
            "warnings": warnings,
            "by_type": by_type,
            "passed": len(violations) == 0,
        }

"""Model-level FDR correction for multiple testing bias.

When comparing multiple model configurations (e.g., different
hyperparameters, different feature sets) and selecting the best by
Sharpe ratio, the selection is subject to multiple testing bias.
This module provides functions to:

1. Convert a Sharpe ratio to a p-value via the standard t-test.
2. Apply Benjamini-Hochberg FDR correction across a batch of model
   comparison results.
"""

from __future__ import annotations

import math

from scipy import stats

from src.common.logging import get_logger
from src.research.factor_scanner import benjamini_hochberg_correction

log = get_logger(__name__)


def compute_model_p_value(
    sharpe: float,
    n_obs: int,
    n_params: int = 1,
) -> float:
    """Convert a Sharpe ratio to a two-sided p-value.

    Uses the standard t-test: t = sharpe * sqrt(n_obs), with
    df = n_obs - n_params.  This tests the null hypothesis that the
    true Sharpe ratio is zero.

    Parameters
    ----------
    sharpe:
        Annualised (or period) Sharpe ratio of the model.
    n_obs:
        Number of independent observations (e.g. trading days).
    n_params:
        Number of estimated model parameters (default 1).  Used to
        compute degrees of freedom.

    Returns
    -------
    float
        Two-sided p-value from the t-distribution.  Returns 1.0 when
        *n_obs* is too small for a meaningful test.
    """
    if n_obs <= n_params:
        return 1.0
    df = n_obs - n_params
    t_stat = sharpe * math.sqrt(n_obs)
    return float(2 * (1 - stats.t.cdf(abs(t_stat), df=df)))


def apply_model_fdr(
    model_results: list[dict],
    alpha: float = 0.05,
) -> list[dict]:
    """Apply FDR correction to a batch of model comparison results.

    Each element of *model_results* must be a dict with at least:

    - ``"model_id"`` -- unique identifier for the model configuration
    - ``"sharpe"``   -- Sharpe ratio
    - ``"ic"``       -- information coefficient (informational, carried through)
    - ``"p_value"``  -- pre-computed p-value; **if missing or None**,
      it is derived from *sharpe* and ``n_obs`` via
      :func:`compute_model_p_value`.

    If ``p_value`` is not present the caller **must** supply ``n_obs``
    (and optionally ``n_params``) in each dict so that the p-value can
    be computed.

    Parameters
    ----------
    model_results:
        List of model result dicts (see above).
    alpha:
        FDR threshold (default 0.05).

    Returns
    -------
    list[dict]
        The same list, mutated in-place **and** returned, with two
        additional keys per entry:

        - ``adjusted_p_value`` -- Benjamini-Hochberg adjusted p-value
        - ``fdr_significant``  -- ``True`` if the adjusted p-value <= alpha
    """
    if not model_results:
        return model_results

    # Derive any missing p-values from Sharpe ratios
    for mr in model_results:
        if mr.get("p_value") is None:
            n_obs = mr.get("n_obs", 252)  # default: one year of daily data
            n_params = mr.get("n_params", 1)
            mr["p_value"] = compute_model_p_value(
                sharpe=mr["sharpe"],
                n_obs=n_obs,
                n_params=n_params,
            )

    p_values = [mr["p_value"] for mr in model_results]
    significant_mask, adjusted_p_values = benjamini_hochberg_correction(
        p_values, alpha=alpha,
    )

    for i, mr in enumerate(model_results):
        mr["adjusted_p_value"] = adjusted_p_values[i]
        mr["fdr_significant"] = significant_mask[i]

    n_sig = sum(1 for mr in model_results if mr["fdr_significant"])
    log.info(
        "model_fdr_applied",
        n_models=len(model_results),
        alpha=alpha,
        n_fdr_significant=n_sig,
    )

    return model_results

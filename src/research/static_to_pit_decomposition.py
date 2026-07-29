"""Public static-to-PIT diagnostic surface.

The implementation is split by responsibility so the canonical research engine
is not duplicated: contract gates, pure diagnostics, metric effects, reporting,
per-window execution, and repository orchestration.
"""

from src.research.static_to_pit_contract import (
    CELL_ORDER,
    DecompositionCell,
    build_four_cell_matrix,
    canonical_sha256,
    final_stop_decision,
    validate_endpoint_reproduction,
    validate_frozen_spec_pair,
)
from src.research.static_to_pit_diagnostics import (
    contribution_gap,
    label_bin_migration,
    score_rank_migration,
    selected_return_contributions,
    selection_overlap,
    symbol_membership_categories,
    topk_selections,
)
from src.research.static_to_pit_effects import (
    DECOMPOSITION_METRICS,
    extract_original_candidate_metrics,
    four_cell_effects,
)

__all__ = [
    "CELL_ORDER",
    "DECOMPOSITION_METRICS",
    "DecompositionCell",
    "build_four_cell_matrix",
    "canonical_sha256",
    "contribution_gap",
    "extract_original_candidate_metrics",
    "final_stop_decision",
    "four_cell_effects",
    "label_bin_migration",
    "score_rank_migration",
    "selected_return_contributions",
    "selection_overlap",
    "symbol_membership_categories",
    "topk_selections",
    "validate_endpoint_reproduction",
    "validate_frozen_spec_pair",
]

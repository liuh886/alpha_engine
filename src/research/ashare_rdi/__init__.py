"""Research-only A-share risk density study contracts.

No live strategy registration, investment signals or automatic publication.
"""

from .contracts import RiskEvent, event_exposure_timeline
from .outcomes import PriceBar, forward_outcomes

__all__ = ["RiskEvent", "event_exposure_timeline", "PriceBar", "forward_outcomes"]

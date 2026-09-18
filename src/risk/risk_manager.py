import math
from dataclasses import dataclass
from typing import Any, Dict, List

from src.models.schemas import FinancialRecommendation


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    allocation_pct: float
    reasons: List[str]

    @property
    def blocked(self) -> bool:
        return not self.approved


class RiskManager:
    """Deterministic re-check of the risk rules the LLM is only *told* to follow.

    The system prompt asks the model to cap allocation at 5% and require 70%
    confidence, but a prompt is not an enforcement mechanism - a model can
    misread, drift, or hallucinate past it. This re-validates every
    recommendation in plain Python before it can ever reach an order.
    """

    def __init__(
        self,
        max_allocation_pct: float = 5.0,
        min_confidence: int = 70,
        max_daily_trades: int = 3,
    ):
        self.max_allocation_pct = max_allocation_pct
        self.min_confidence = min_confidence
        self.max_daily_trades = max_daily_trades

    def evaluate(
        self,
        recommendation: FinancialRecommendation,
        market_data: Dict[str, Any],
        fundamental_data: Dict[str, Any],
        trades_today: int,
    ) -> RiskDecision:
        # Reasons are tracked in two buckets rather than inferred from message
        # text, so a later wording change can never silently flip whether a
        # reason blocks the trade.
        blocking_reasons: List[str] = []
        info_reasons: List[str] = []

        if recommendation.recommendation == "HOLD":
            blocking_reasons.append("Recommendation is HOLD; no order to place.")
            return RiskDecision(approved=False, allocation_pct=0.0, reasons=blocking_reasons)

        if "error" in market_data:
            blocking_reasons.append(f"Market data unavailable: {market_data['error']}")
        if "error" in fundamental_data:
            blocking_reasons.append(f"Fundamental data unavailable: {fundamental_data['error']}")

        if recommendation.confidence < self.min_confidence:
            blocking_reasons.append(
                f"Confidence {recommendation.confidence}% is below the "
                f"{self.min_confidence}% minimum required to execute."
            )

        if trades_today >= self.max_daily_trades:
            blocking_reasons.append(
                f"Daily trade limit reached ({trades_today}/{self.max_daily_trades})."
            )

        # The Pydantic schema already hard-caps suggested_allocation_pct at 5%,
        # but a deployment can configure an even stricter max_allocation_pct.
        allocation_pct = min(recommendation.suggested_allocation_pct, self.max_allocation_pct)
        if recommendation.suggested_allocation_pct > self.max_allocation_pct:
            info_reasons.append(
                f"LLM suggested {recommendation.suggested_allocation_pct}% allocation; "
                f"clamped to the configured {self.max_allocation_pct}% cap."
            )
        if allocation_pct <= 0:
            blocking_reasons.append("Computed allocation is zero or negative.")

        approved = len(blocking_reasons) == 0
        return RiskDecision(
            approved=approved,
            allocation_pct=allocation_pct,
            reasons=blocking_reasons + info_reasons,
        )

    def size_order(self, allocation_pct: float, account_equity: float, price: float) -> int:
        """Whole-share quantity for the given allocation percentage."""
        if math.isnan(price) or math.isnan(account_equity) or price <= 0 or account_equity <= 0:
            return 0
        budget = account_equity * (allocation_pct / 100.0)
        return int(budget // price)

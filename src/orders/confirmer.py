from abc import ABC, abstractmethod
from typing import List

from src.broker.base import Broker
from src.models.schemas import FinancialRecommendation
from src.notifications.telegram import TelegramNotifier, escape_markdown, notify_safely
from src.orders.store import EXECUTED, EXECUTION_FAILED, OrderStore, status_for_fill


class Confirmer(ABC):
    """Decides whether a risk-approved order gets executed immediately or
    held for a human's go-ahead. Swapping HumanConfirmer for
    AutonomousConfirmer (via EXECUTION_MODE) is the entire migration path to
    unattended trading - no other code changes.
    """

    @abstractmethod
    def handle(
        self,
        ticker: str,
        quantity: int,
        allocation_pct: float,
        recommendation: FinancialRecommendation,
        risk_reasons: List[str],
    ) -> None:
        ...

    @staticmethod
    def _rationale_block(recommendation: FinancialRecommendation) -> str:
        # All of this is LLM-generated free text - escape it before it goes
        # into a Markdown-formatted Telegram message, or a stray '_'/'*' in
        # the model's own wording breaks the send entirely.
        r = recommendation.rationale
        return (
            f"Technical: {escape_markdown(r.technical_factors)}\n"
            f"Fundamental: {escape_markdown(r.fundamental_factors)}\n"
            f"Sentiment: {escape_markdown(r.sentiment_factors)}\n"
            f"Risks: {escape_markdown(recommendation.risks)}"
        )

    @staticmethod
    def _risk_notes(risk_reasons: List[str]) -> str:
        if not risk_reasons:
            return ""
        return f"\nRisk notes: {escape_markdown('; '.join(risk_reasons))}"


class HumanConfirmer(Confirmer):
    def __init__(self, store: OrderStore, notifier: TelegramNotifier):
        self.store = store
        self.notifier = notifier

    def handle(
        self,
        ticker: str,
        quantity: int,
        allocation_pct: float,
        recommendation: FinancialRecommendation,
        risk_reasons: List[str],
    ) -> None:
        side = recommendation.recommendation
        ticker_display = escape_markdown(ticker)
        order = self.store.create_pending(
            ticker, side, quantity, allocation_pct, recommendation.confidence,
            reasons="; ".join(risk_reasons),
        )
        risk_notes = self._risk_notes(risk_reasons)
        message = (
            f"*Proposed order #{order.id}*\n"
            f"{side} {quantity} {ticker_display}\n"
            f"Allocation: {allocation_pct:.2f}%  |  Confidence: {recommendation.confidence}%\n\n"
            f"{self._rationale_block(recommendation)}"
            f"{risk_notes}\n\n"
            f"Reply `/confirm_{order.id}` to execute or `/reject_{order.id}` to discard.\n"
            f"Run `check-confirmations` after replying to execute."
        )
        # If this notification fails to send, the order still exists as PENDING
        # (it will simply expire via TTL if nobody ever learns about it) - print
        # it so it's at least visible in whatever is running this command.
        print(message)
        notify_safely(self.notifier, message)


class AutonomousConfirmer(Confirmer):
    def __init__(self, store: OrderStore, notifier: TelegramNotifier, broker: Broker):
        self.store = store
        self.notifier = notifier
        self.broker = broker

    def handle(
        self,
        ticker: str,
        quantity: int,
        allocation_pct: float,
        recommendation: FinancialRecommendation,
        risk_reasons: List[str],
    ) -> None:
        side = recommendation.recommendation
        ticker_display = escape_markdown(ticker)
        order = self.store.create_pending(
            ticker, side, quantity, allocation_pct, recommendation.confidence,
            reasons="; ".join(risk_reasons),
        )
        risk_notes = self._risk_notes(risk_reasons)

        # connect() and place_order() share one try/except: a Gateway that's
        # down or unreachable must fail the order the same way a broker-side
        # rejection does, not crash uncaught and skip notifying anyone.
        try:
            try:
                self.broker.connect()
                result = self.broker.place_order(ticker, side, quantity)
            finally:
                self.broker.disconnect()
        except Exception as e:
            self.store.update_status(order.id, EXECUTION_FAILED)
            notify_safely(
                self.notifier,
                f"*Order #{order.id} failed to execute autonomously*\n"
                f"{side} {quantity} {ticker_display}\nError: {escape_markdown(str(e))}",
            )
            return

        status = status_for_fill(result.status)
        self.store.update_status(order.id, status, ibkr_order_id=result.broker_order_id)
        label = "executed" if status == EXECUTED else "submitted (not yet filled)"
        notify_safely(
            self.notifier,
            f"*Order #{order.id} {label} autonomously*\n"
            f"{side} {quantity} {ticker_display}\n"
            f"Broker status: {result.status} (filled {result.filled_quantity})\n\n"
            f"{self._rationale_block(recommendation)}"
            f"{risk_notes}",
        )


def build_confirmer(execution_mode: str, store: OrderStore, notifier: TelegramNotifier, broker: Broker) -> Confirmer:
    if execution_mode == "autonomous":
        return AutonomousConfirmer(store, notifier, broker)
    return HumanConfirmer(store, notifier)

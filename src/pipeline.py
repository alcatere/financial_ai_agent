import threading
from datetime import date
from typing import Optional

from src.agent.financial_agent import analyze_asset, llm_unreachable_reason
from src.broker.ibkr import IBKRBroker
from src.config import Config
from src.models.schemas import FinancialRecommendation
from src.notifications.telegram import TelegramNotifier, escape_markdown, notify_safely
from src.orders.confirmer import build_confirmer
from src.orders.store import CONFIRMED, EXECUTED, EXECUTION_FAILED, OrderStore, PENDING, REJECTED, status_for_fill
from src.risk.risk_manager import RiskDecision, RiskManager


def run_analysis(ticker: str, config: Config) -> None:
    # Escaped once for every Telegram message in this function; `ticker`
    # itself stays raw for broker calls, logging, and comparisons.
    ticker_display = escape_markdown(ticker)
    store = OrderStore(config.orders_db_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    broker = IBKRBroker(config.ibkr_host, config.ibkr_port, config.ibkr_client_id)
    risk_manager = RiskManager(
        max_allocation_pct=config.max_allocation_pct,
        min_confidence=config.min_confidence,
        max_daily_trades=config.max_daily_trades,
    )

    expired = store.expire_stale(config.pending_order_ttl_minutes)
    if expired:
        print(f"[*] Expired {expired} stale pending order(s).")

    unreachable = llm_unreachable_reason(config)
    if unreachable:
        raise RuntimeError(unreachable)

    print(f"[*] Analyzing {ticker}...")
    analysis = analyze_asset(ticker, config)
    rec = analysis.recommendation

    print(f"[*] Recommendation: {rec.recommendation} (confidence {rec.confidence}%)")
    print(f"    Technical: {rec.rationale.technical_factors}")
    print(f"    Fundamental: {rec.rationale.fundamental_factors}")
    print(f"    Sentiment: {rec.rationale.sentiment_factors}")
    print(f"    Risks: {rec.risks}")

    trades_today = store.count_executed_today()
    decision = risk_manager.evaluate(
        rec, analysis.market_data, analysis.fundamental_data, trades_today
    )

    for reason in decision.reasons:
        print(f"    - {reason}")

    if decision.blocked:
        print(f"[!] Risk manager blocked this trade for {ticker}. No order created.")
        notify_safely(
            notifier,
            f"*{ticker_display}*: {rec.recommendation} suggested but blocked by risk checks.\n"
            + escape_markdown("\n".join(decision.reasons)),
        )
        return

    broker.connect()
    try:
        equity = broker.get_account_equity()
        # Contracts are hardcoded to SMART/USD (see src/broker/ibkr.py) - this
        # only trades USD-denominated US-listed symbols for now, not BMV/MXN.
        held_position = broker.get_position(ticker) if rec.recommendation == "SELL" else None
    finally:
        broker.disconnect()

    if rec.recommendation == "SELL":
        held_qty_raw = held_position.quantity if held_position else 0.0
        if held_qty_raw < 0:
            print(f"[!] SELL suggested for {ticker} but the account is already short {-held_qty_raw} shares; skipping.")
            notify_safely(
                notifier,
                f"*{ticker_display}*: SELL suggested but the account is already short {-held_qty_raw} shares. "
                f"Skipped to avoid increasing the short.",
            )
            return
        if held_qty_raw == 0:
            print(f"[!] SELL suggested for {ticker} but no position is held; skipping to avoid opening a short.")
            notify_safely(
                notifier,
                f"*{ticker_display}*: SELL suggested but no position is held. Skipped (would have opened a short).",
            )
            return
        if held_qty_raw < 1:
            print(f"[!] SELL suggested for {ticker} but the position ({held_qty_raw}) is less than one whole share; skipping.")
            notify_safely(
                notifier,
                f"*{ticker_display}*: SELL suggested but the held position ({held_qty_raw} shares) is smaller than "
                f"the minimum this system can sell (whole shares only). Skipped.",
            )
            return
        held_qty = int(held_qty_raw)

    current_price = analysis.market_data.get("current_price", 0) or 0
    quantity = risk_manager.size_order(decision.allocation_pct, equity, current_price)
    if rec.recommendation == "SELL":
        quantity = min(quantity, held_qty)

    if quantity <= 0:
        print(f"[!] Computed order size is 0 shares for {ticker}; skipping.")
        notify_safely(notifier, f"*{ticker_display}*: {rec.recommendation} approved but sized to 0 shares. Skipped.")
        return

    confirmer = build_confirmer(config.execution_mode, store, notifier, broker)
    confirmer.handle(
        ticker=ticker,
        quantity=quantity,
        allocation_pct=decision.allocation_pct,
        recommendation=rec,
        risk_reasons=decision.reasons,
    )
    print(f"[*] Order handed off to {config.execution_mode} confirmer.")


def run_check_confirmations(config: Config) -> None:
    store = OrderStore(config.orders_db_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    broker = IBKRBroker(config.ibkr_host, config.ibkr_port, config.ibkr_client_id_confirmations)

    expired = store.expire_stale(config.pending_order_ttl_minutes)
    if expired:
        print(f"[*] Expired {expired} stale pending order(s).")

    stuck = store.flag_stuck_confirmed(config.pending_order_ttl_minutes)
    for order in stuck:
        print(f"[!] Order #{order.id} stuck in CONFIRMED - flagged for manual review.")
        notify_safely(
            notifier,
            f"*Order #{order.id} needs manual review*\n"
            f"{order.side} {order.quantity} {escape_markdown(order.ticker)} was confirmed but the process "
            f"never reported placing it with the broker. Check IBKR and orders.db directly "
            f"before doing anything - it may or may not have actually been sent.",
        )

    updates = notifier.get_updates()
    if not updates:
        print("[*] No new Telegram replies.")
        return

    broker.connect()
    try:
        for update in updates:
            reply = notifier.parse_confirmation(update)
            if reply is None:
                notifier.ack(update["update_id"])
                continue

            try:
                order = store.get(reply.order_id)
                if order is None or order.status != PENDING:
                    print(f"[!] Reply for order #{reply.order_id} ignored (not pending or unknown).")
                elif not reply.approved:
                    store.update_status(order.id, REJECTED)
                    notify_safely(notifier, f"Order #{order.id} rejected.")
                else:
                    store.update_status(order.id, CONFIRMED)
                    # Only a failure from place_order itself means the trade
                    # didn't go through - a failure to *notify* about a
                    # successful trade must never reclassify it as failed.
                    try:
                        result = broker.place_order(order.ticker, order.side, order.quantity)
                    except Exception as e:
                        print(f"[!] Failed to place order #{order.id}: {e}")
                        store.update_status(order.id, EXECUTION_FAILED)
                        notify_safely(
                            notifier,
                            f"Order #{order.id} confirmed but execution failed: {escape_markdown(str(e))}\n"
                            f"It will NOT be retried automatically - check IBKR and orders.db.",
                        )
                    else:
                        status = status_for_fill(result.status)
                        store.update_status(order.id, status, ibkr_order_id=result.broker_order_id)
                        label = "executed" if status == EXECUTED else "submitted (not yet filled)"
                        print(f"[*] Order #{order.id} {label}: {result.status}")
                        notify_safely(
                            notifier,
                            f"*Order #{order.id} {label}*\n"
                            f"{order.side} {order.quantity} {escape_markdown(order.ticker)}\n"
                            f"Broker status: {result.status} (filled {result.filled_quantity})",
                        )
            except Exception as e:
                # Anything unexpected outside the place_order path (e.g. a
                # store/database error) - log it, but don't guess at an order
                # status we're not sure of.
                print(f"[!] Unexpected error handling reply for order #{reply.order_id}: {e}")
            finally:
                notifier.ack(update["update_id"])
    finally:
        broker.disconnect()


MAX_REASON_CHARS = 220


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _short_reason(recommendation: FinancialRecommendation) -> str:
    r = recommendation.rationale
    text = (r.fundamental_factors or r.technical_factors or r.sentiment_factors or "").strip()
    # Escaped BEFORE truncating: escape_markdown can add characters (each
    # special char becomes two), so truncating first would let the escaped
    # result exceed MAX_REASON_CHARS - truncating the already-escaped text is
    # what actually bounds the final length.
    return _truncate(escape_markdown(text), MAX_REASON_CHARS)


def format_digest_line(
    ticker: str,
    recommendation: Optional[FinancialRecommendation],
    decision: Optional[RiskDecision],
    error: Optional[str] = None,
    data_unavailable: bool = False,
) -> str:
    """Pure formatting: one line per ticker for the daily digest message.

    `data_unavailable` is an explicit flag the caller computes from the raw
    market/fundamental data (not inferred from RiskManager's reason *text*,
    which is free-form and not a contract this function should depend on).

    Kept side-effect-free and network-free so it's directly unit testable.
    """
    ticker_display = escape_markdown(ticker)

    if error is not None:
        return f"⚠️ *{ticker_display}*: no se pudo analizar hoy ({_truncate(escape_markdown(error), MAX_REASON_CHARS)})"

    if recommendation is None:
        raise ValueError(f"recommendation is required when no error is given (ticker={ticker})")
    if decision is None:
        raise ValueError(f"decision is required when no error is given (ticker={ticker})")

    if recommendation.recommendation == "HOLD":
        # A HOLD caused by missing/errored market or fundamental data (the
        # system prompt tells the LLM to prefer HOLD when data is missing)
        # must not read as "checked and it's fine".
        if data_unavailable:
            note = _truncate(escape_markdown("; ".join(decision.reasons)), MAX_REASON_CHARS)
            return f"➡️ *{ticker_display}*: sin datos suficientes hoy ({note})"
        return f"➡️ *{ticker_display}*: mantente, está estable. {_short_reason(recommendation)}"

    if decision.approved:
        verb = "COMPRA" if recommendation.recommendation == "BUY" else "VENDE"
        emoji = "🟢" if recommendation.recommendation == "BUY" else "🔴"
        return (
            f"{emoji} *{ticker_display}*: {verb} (confianza {recommendation.confidence}%). "
            f"{_short_reason(recommendation)}"
        )

    reasons = _truncate(escape_markdown("; ".join(decision.reasons)), MAX_REASON_CHARS)
    return f"➡️ *{ticker_display}*: sin acción clara ({reasons})"


TELEGRAM_MESSAGE_SOFT_LIMIT = 3800  # margin under Telegram's 4096-char hard limit


def build_digest_messages(header: str, lines: list) -> list:
    """Groups per-ticker digest lines into one or more messages under
    Telegram's length limit. A long watchlist or verbose rationale must
    degrade to several messages, not fail to send at all.
    """
    chunks: list = [[]]
    current_len = len(header)
    for line in lines:
        addition = len(line) + 2  # "\n\n" separator
        if current_len + addition > TELEGRAM_MESSAGE_SOFT_LIMIT and chunks[-1]:
            chunks.append([])
            current_len = len(header)
        chunks[-1].append(line)
        current_len += addition

    multi = len(chunks) > 1
    messages = []
    for i, chunk in enumerate(chunks, start=1):
        title = f"{header} (parte {i}/{len(chunks)})" if multi else header
        messages.append(title + "\n\n" + "\n\n".join(chunk))
    return messages


def _analyze_with_timeout(ticker: str, config: Config, timeout_seconds: float):
    """Runs analyze_asset on a daemon thread with a wall-clock timeout.

    A single stuck ticker (network/LLM hang, no underlying timeout of its
    own) must not block the rest of the watchlist - or, worse, keep the
    whole `daily-digest` process alive past its scheduled run. The thread is
    daemonized so an actually-hung call never prevents process exit; we just
    stop waiting on it and move on.
    """
    result: dict = {}

    def target():
        try:
            result["value"] = analyze_asset(ticker, config)
        except BaseException as e:
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise TimeoutError(f"analysis did not complete within {timeout_seconds:.0f}s")
    if "error" in result:
        err = result["error"]
        # Re-raise as-is when it's an ordinary Exception (the common case)
        # so callers using a normal `except Exception` still catch it. A
        # non-Exception BaseException (SystemExit, GeneratorExit, ...) is
        # wrapped instead of re-raised bare: the caller's per-ticker
        # `except Exception` must not have to become `except BaseException`
        # (which would also swallow a user's Ctrl+C) just to stay isolated.
        if isinstance(err, Exception):
            raise err
        raise RuntimeError(f"non-Exception error during analysis: {err!r}") from err
    return result["value"]


def run_daily_digest(config: Config) -> None:
    """Advisory-only: analyzes the watchlist and sends one Telegram digest.

    Never places or proposes an order - the user executes manually in their
    own broker (GBM). One bad ticker (data/LLM failure, or a hang) must not
    silence the rest of the digest, so each ticker's analysis is isolated
    and time-bounded.
    """
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    risk_manager = RiskManager(
        max_allocation_pct=config.max_allocation_pct, min_confidence=config.min_confidence
    )

    unreachable = llm_unreachable_reason(config)
    if unreachable:
        print(f"[!] {unreachable}")
        notify_safely(
            notifier,
            f"*Resumen diario — {date.today().isoformat()}*\n\n"
            f"⚠️ No se pudo generar el análisis de hoy.\n{escape_markdown(unreachable)}",
        )
        return

    lines = []
    for ticker in config.watchlist:
        try:
            print(f"[*] Analyzing {ticker}...")
            analysis = _analyze_with_timeout(ticker, config, config.analysis_timeout_seconds)
            decision = risk_manager.evaluate_signal(
                analysis.recommendation, analysis.market_data, analysis.fundamental_data
            )
            data_unavailable = "error" in analysis.market_data or "error" in analysis.fundamental_data
            lines.append(
                format_digest_line(ticker, analysis.recommendation, decision, data_unavailable=data_unavailable)
            )
        except Exception as e:
            print(f"[!] Failed to analyze {ticker}: {e}")
            lines.append(format_digest_line(ticker, None, None, error=str(e)))

    header = f"*Resumen diario — {date.today().isoformat()}*"
    for message in build_digest_messages(header, lines):
        print(message)
        notify_safely(notifier, message)

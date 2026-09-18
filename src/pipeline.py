from src.agent.financial_agent import analyze_asset
from src.broker.ibkr import IBKRBroker
from src.config import Config
from src.notifications.telegram import TelegramNotifier, notify_safely
from src.orders.confirmer import build_confirmer
from src.orders.store import CONFIRMED, EXECUTED, EXECUTION_FAILED, OrderStore, PENDING, REJECTED, status_for_fill
from src.risk.risk_manager import RiskManager


def run_analysis(ticker: str, config: Config) -> None:
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
            f"*{ticker}*: {rec.recommendation} suggested but blocked by risk checks.\n"
            + "\n".join(decision.reasons),
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
                f"*{ticker}*: SELL suggested but the account is already short {-held_qty_raw} shares. "
                f"Skipped to avoid increasing the short.",
            )
            return
        if held_qty_raw == 0:
            print(f"[!] SELL suggested for {ticker} but no position is held; skipping to avoid opening a short.")
            notify_safely(
                notifier,
                f"*{ticker}*: SELL suggested but no position is held. Skipped (would have opened a short).",
            )
            return
        if held_qty_raw < 1:
            print(f"[!] SELL suggested for {ticker} but the position ({held_qty_raw}) is less than one whole share; skipping.")
            notify_safely(
                notifier,
                f"*{ticker}*: SELL suggested but the held position ({held_qty_raw} shares) is smaller than "
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
        notify_safely(notifier, f"*{ticker}*: {rec.recommendation} approved but sized to 0 shares. Skipped.")
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
            f"{order.side} {order.quantity} {order.ticker} was confirmed but the process "
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
                            f"Order #{order.id} confirmed but execution failed: {e}\n"
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
                            f"{order.side} {order.quantity} {order.ticker}\n"
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

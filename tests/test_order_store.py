import os
import pytest
from src.orders.store import (
    CONFIRMED,
    EXECUTED,
    EXPIRED,
    PENDING,
    REJECTED,
    STUCK,
    SUBMITTED,
    OrderStore,
    status_for_fill,
)


@pytest.fixture
def store(tmp_path):
    return OrderStore(str(tmp_path / "orders.db"))


def test_create_and_get_pending(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    assert order.status == PENDING
    fetched = store.get(order.id)
    assert fetched.ticker == "AAPL"
    assert fetched.quantity == 5


def test_list_pending_only_returns_pending(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    store.create_pending("MSFT", "SELL", 2, 2.0, 90)
    store.update_status(order.id, CONFIRMED)

    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].ticker == "MSFT"


def test_update_status_sets_broker_order_id(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    store.update_status(order.id, EXECUTED, ibkr_order_id="12345")
    fetched = store.get(order.id)
    assert fetched.status == EXECUTED
    assert fetched.ibkr_order_id == "12345"


def test_count_executed_today(store):
    o1 = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    o2 = store.create_pending("MSFT", "BUY", 2, 2.0, 90)
    store.create_pending("TSLA", "BUY", 1, 1.0, 95)  # stays pending

    store.update_status(o1.id, EXECUTED)
    store.update_status(o2.id, EXECUTED)

    assert store.count_executed_today() == 2


def test_expire_stale_orders(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    expired_count = store.expire_stale(ttl_minutes=0)
    assert expired_count == 1
    assert store.get(order.id).status == EXPIRED


def test_expire_stale_does_not_touch_confirmed_orders(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    store.update_status(order.id, CONFIRMED)
    store.expire_stale(ttl_minutes=0)
    assert store.get(order.id).status == CONFIRMED


def test_flag_stuck_confirmed(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    store.update_status(order.id, CONFIRMED)
    stuck = store.flag_stuck_confirmed(ttl_minutes=0)
    assert len(stuck) == 1
    assert stuck[0].id == order.id
    assert store.get(order.id).status == STUCK


def test_flag_stuck_confirmed_ignores_recent_confirmations(store):
    order = store.create_pending("AAPL", "BUY", 5, 3.0, 80)
    store.update_status(order.id, CONFIRMED)
    stuck = store.flag_stuck_confirmed(ttl_minutes=120)
    assert stuck == []
    assert store.get(order.id).status == CONFIRMED


def test_status_for_fill_maps_filled_to_executed():
    assert status_for_fill("Filled") == EXECUTED


def test_status_for_fill_maps_other_statuses_to_submitted():
    assert status_for_fill("Submitted") == SUBMITTED
    assert status_for_fill("PreSubmitted") == SUBMITTED

import time
from typing import Optional

from ib_async import IB, MarketOrder, Stock

from src.broker.base import Broker, OrderResult, Position

# This MVP only trades USD-denominated, SMART-routed US-listed stocks. IBKR
# itself supports BMV/MXN and other markets, but that needs explicit
# exchange/currency routing per contract that isn't implemented here yet -
# don't widen get_position's matching beyond what place_order actually trades.
EXCHANGE = "SMART"
CURRENCY = "USD"


class IBKRBroker(Broker):
    """Connects to a locally-running IB Gateway/TWS that the user has already
    logged into. We never store or handle IBKR credentials in this codebase -
    IBKR's own Gateway app owns authentication and 2FA.
    """

    def __init__(self, host: str, port: int, client_id: int):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def connect(self) -> None:
        if not self.ib.isConnected():
            self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=10)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def get_account_equity(self) -> float:
        for value in self.ib.accountSummary():
            if value.tag == "NetLiquidation":
                return float(value.value)
        raise RuntimeError("Could not read NetLiquidation from IBKR account summary")

    def get_position(self, ticker: str) -> Optional[Position]:
        for position in self.ib.positions():
            contract = position.contract
            if contract.symbol == ticker and contract.currency == CURRENCY:
                return Position(
                    ticker=ticker,
                    quantity=position.position,
                    avg_cost=position.avgCost,
                )
        return None

    def place_order(self, ticker: str, side: str, quantity: int, timeout_seconds: float = 60.0) -> OrderResult:
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Unsupported side: {side}")
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        contract = Stock(ticker, EXCHANGE, CURRENCY)
        self.ib.qualifyContracts(contract)
        order = MarketOrder(side, quantity)
        trade = self.ib.placeOrder(contract, order)

        deadline = time.monotonic() + timeout_seconds
        while not trade.isDone() and trade.orderStatus.status not in ("Filled", "Cancelled"):
            if time.monotonic() >= deadline:
                # Order is still live at the broker (e.g. resting outside market
                # hours) - stop waiting so a caller like a cron job never hangs.
                # Its real status can be checked directly in IBKR.
                break
            self.ib.waitOnUpdate(timeout=5)

        return OrderResult(
            broker_order_id=str(trade.order.orderId),
            status=trade.orderStatus.status,
            filled_quantity=trade.orderStatus.filled,
        )

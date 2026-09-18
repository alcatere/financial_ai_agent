from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_cost: float


@dataclass
class OrderResult:
    broker_order_id: str
    status: str
    filled_quantity: float


class Broker(ABC):
    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def get_account_equity(self) -> float:
        ...

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]:
        ...

    @abstractmethod
    def place_order(self, ticker: str, side: str, quantity: int) -> OrderResult:
        ...

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from threading import Timer
import typing
from ibapi.common import TickerId, TickAttrib
from ibapi.ticktype import TickType
from enum import Enum, auto
from queue import Queue
from dataclasses import dataclass

#TIMEOUT = 20


class Future(Enum):
    mnq = auto()
    mes = auto()


class OrderType(Enum):
    lmt = auto()
    stp_lmt = auto()


@dataclass
class BracketOrder:
    market_is_rising: bool
    fut: Future
    order_type: OrderType
    parent_price: float
    parent_order_id: typing.Optional[int] = None
    order_size: int = 1

    def __post_init__(self):
        if type(self.market_is_rising) != bool:
            raise ValueError("Invalid buy or sell type")
        if type(self.fut) != Future:
            raise ValueError("invalid contract selection")
        self.parent_price = round(self.parent_price*4)/4

    def get_contract(self) -> Contract:
        contract = Contract()
        contract.secType = "FUT"
        contract.exchange = "GLOBEX"
        contract.currency = "USD"
        if self.fut == Future.mnq:
            contract.localSymbol = "MNQU0"
            return contract
        if self.fut == Future.mes:
            contract.localSymbol = "MESU0"
            return contract

    def get_parent_order(self, order_id: int) -> Order:
        self.parent_order_id = order_id
        return self._get_stp_lmt_parent() if self.order_type == OrderType.stp_lmt else self._get_lmt_parent()

    def get_profit_taker(self) -> Order:
        profit_taker = Order()
        profit_taker.action = "SELL" if self.market_is_rising else "BUY"
        profit_taker.totalQuantity = self.order_size
        profit_taker.orderType = "LMT"
        profit_taker.lmtPrice = self.parent_price + self._calc_profit_taker_offset()
        profit_taker.parentId = self.parent_order_id
        profit_taker.tif = "GTC"
        profit_taker.transmit = False
        return profit_taker

    def get_stop_loss(self) -> Order:
        stop_loss = Order()
        stop_loss.action = "SELL" if self.market_is_rising else "BUY"
        stop_loss.totalQuantity = self.order_size
        stop_loss.orderType = "STP LMT"
        stop_loss.lmtPrice = (self.parent_price + 1) if self.market_is_rising else (self.parent_price - 1)
        stop_loss.auxPrice = self.parent_price - self._calc_initial_stop_price()
        stop_loss.adjustedOrderType = "TRAIL LIMIT"
        stop_loss.adjustedStopPrice = self.parent_price + self._adjusted_stop_offset()
        stop_loss.adjustedStopLimitPrice = self.parent_price + self._adjusted_stop_limit_offset()
        stop_loss.triggerPrice = self.parent_price + self._trigger_price_offset()
        stop_loss.adjustedTrailingAmount = 10 if self.fut == Future.mnq else 4
        stop_loss.tif = "GTC"
        stop_loss.outsideRth = True
        stop_loss.parentId = self.parent_order_id
        # stop_loss.triggerMethod = 3
        stop_loss.transmit = False
        return stop_loss

    def _calc_initial_stop_price(self) -> float:
        offset = 10 if self.fut == Future.mnq else 5
        if not self.market_is_rising:
            offset = -1 * offset
        return offset

    def _calc_profit_taker_offset(self) -> float:
        offset = 25 if self.fut == Future.mnq else 15
        if not self.market_is_rising:
            offset = -1 * offset
        return offset

    def _adjusted_stop_offset(self) -> float:
        offset = 4 if self.fut == Future.mnq else 2
        if not self.market_is_rising:
            offset = -1 * offset
        return offset

    def _adjusted_stop_limit_offset(self) -> float:
        offset = 2 if self.fut == Future.mnq else 1
        if not self.market_is_rising:
            offset = -1 * offset
        return offset

    def _trigger_price_offset(self) -> float:
        offset = 10 if self.fut == Future.mnq else 5
        if not self.market_is_rising:
            offset = -1 * offset
        return offset

    def _get_stp_lmt_parent(self) -> Order:
        _order = Order()
        _order.action = "BUY" if self.market_is_rising else "SELL"
        _order.totalQuantity = self.order_size
        _order.orderType = "STP LMT"
        _order.auxPrice = (self.parent_price - 0.25) if self.market_is_rising else (self.parent_price + 0.25)
        _order.lmtPrice = self.parent_price
        _order.triggerMethod = 3
        _order.tif = "GTC"
        _order.outsideRth = True
        _order.transmit = False
        return _order

    def _get_lmt_parent(self) -> Order:
        _order = Order()
        _order.action = "BUY" if self.market_is_rising else "SELL"
        _order.totalQuantity = self.order_size
        _order.orderType = "LMT"
        _order.lmtPrice = self.parent_price
        _order.tif = "GTC"
        _order.transmit = False
        return _order


class Connection(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

        self.last_price: typing.Optional[float] = None
        self.next_order_id: typing.Optional[int] = None
        self.next_order: typing.Optional[BracketOrder] = None

    def error(self, reqId, errorCode, errorString):
        print(f"Error: , {reqId}, {errorCode}, {errorString}")

    def nextValidId(self, orderId: int):
        self.next_order_id = orderId
        print(f'next order ID is {orderId}')
        self.start()

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId,
                    whyHeld, mktCapPrice):
        print("OrderStatus. Id: ", orderId, ", Status: ", status, ", Filled: ", filled, ", Remaining: ", remaining,
              ", LastFillPrice: ", lastFillPrice)

    def openOrder(self, orderId, contract, order, orderState):
        print("OpenOrder. ID:", orderId, contract.symbol, contract.secType, "@", contract.exchange, ":", order.action,
              order.orderType, order.totalQuantity, orderState.status)

    def execDetails(self, reqId, contract, execution):
        print("ExecDetails. ", reqId, contract.symbol, contract.secType, contract.currency, execution.execId,
              execution.orderId, execution.shares, execution.lastLiquidity)

    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float, attrib: TickAttrib):
        if tickType != 4:
            return
        print(f'{reqId}, price: {price}, {tickType}, {attrib}')
        self.last_price = price

    def start(self):
        if self.next_order is None:
            return
        req_id = self.next_order.fut.value
        self.reqMktData(req_id, self.next_order.get_contract(), "", False, False, [])
        self.place_order(self.next_order)

    def place_order(self, bracket_order: BracketOrder):
        if self.next_order_id is None:
            self.next_order = bracket_order
            return

        parent_order_id = self.next_order_id
        contract = bracket_order.get_contract()
        parent_order = bracket_order.get_parent_order(parent_order_id)
        self.placeOrder(parent_order_id, contract, parent_order)

        stop_loss = bracket_order.get_stop_loss()
        self.placeOrder(parent_order_id + 1, contract, stop_loss)
        profit_taker = bracket_order.get_profit_taker()
        self.placeOrder(parent_order_id + 2, contract, profit_taker)
        Timer(2, self.stop).start()

    def stop(self):
        self.done = True
        self.disconnect()


def main():
    app = Connection()
    app.connect("127.0.0.1", 7496, 8)
    bracket_order = BracketOrder(market_is_rising=True, fut=Future.mnq, order_type=OrderType.lmt, parent_price=10550)
    app.place_order(bracket_order=bracket_order)
    app.run()


if __name__ == "__main__":
    main()

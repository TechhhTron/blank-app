from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

from fyers_apiv3.FyersWebsocket import data_ws
from fyers_apiv3.fyersModel import FyersModel


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("SQLITE_DB_PATH", str(BACKEND_DIR / "tradematic.sqlite3")))

ENTRY_START = dt_time(14, 15)
SCAN_STOP = dt_time(14, 50)
MONITOR_STOP = dt_time(15, 30)

STOPLOSS = -25
TARGET = 100
ENTRY_LIMIT_OFFSET = -0.75
PRICE_TICK = 0.05
STOPLIMIT_LIMIT_OFFSET = 3.0
PROTECTIVE_ORDER_RETRIES = 3

ORDER_TYPE_LIMIT = 1
ORDER_TYPE_MARKET = 2
ORDER_TYPE_STOP_LIMIT = 4

CSV_COLUMNS = ["time", "strike price", "ce/pe", "oi chng", "entry", "exit", "result"]
RISK_DIVISORS = {"low": 10, "medium": 5, "high": 2}


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    index_name: str
    index_symbol: str
    strike_step: int
    price_diff_min: float | None
    price_diff_max: float
    spot_offset: float
    tolerance: float
    default_lot_size: int
    trades_file: str


class MultiUserOptionStrategy:
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.users = self.load_active_users()
        self.market_user = self.pick_market_user()
        self.market_fyers = self.make_fyers(self.market_user)

        self.spot_price = None
        self.ce_price = None
        self.pe_price = None
        self.current_atm = None
        self.ce_symbol = None
        self.pe_symbol = None
        self.ce_oi_chng = ""
        self.pe_oi_chng = ""
        self.ce_lot_size = config.default_lot_size
        self.pe_lot_size = config.default_lot_size
        self.current_expiry_date = None
        self.current_expiry_timestamp = None

        self.scan_stopped = False
        self.algo_stopped = False
        self.active_symbols = set()
        self.last_prices = {}
        self.open_trades = []
        self.fyers_by_user_id = {}
        self.ws = None

    def load_active_users(self):
        if not DB_PATH.exists():
            raise RuntimeError(f"Database not found: {DB_PATH}")

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()

        users = []
        for row in rows:
            user = dict(row)
            if int(user.get("subscription_days") or 0) < 1:
                continue
            if str(user.get("index_name") or "").lower() != self.config.index_name.lower():
                continue
            if not user.get("broker_client_id") or not user.get("broker_session_token"):
                continue
            users.append(user)
        return users

    def pick_market_user(self):
        if not self.users:
            raise RuntimeError(f"No eligible {self.config.index_name} users found in database")
        return self.users[0]

    @staticmethod
    def make_fyers(user):
        return FyersModel(
            client_id=user["broker_client_id"],
            token=user["broker_session_token"],
            log_path="",
        )

    def fyers_for_user(self, user):
        user_id = int(user["id"])
        if user_id not in self.fyers_by_user_id:
            self.fyers_by_user_id[user_id] = self.make_fyers(user)
        return self.fyers_by_user_id[user_id]

    def get_atm(self, spot):
        return round(spot / self.config.strike_step) * self.config.strike_step

    def spot_condition(self, spot, atm):
        return (
            abs(spot - (atm + self.config.spot_offset)) <= self.config.tolerance
            or abs(spot - (atm - self.config.spot_offset)) <= self.config.tolerance
        )

    @staticmethod
    def parse_expiry_date(raw_value):
        if raw_value in (None, ""):
            return None
        if isinstance(raw_value, (int, float)):
            if raw_value > 10_000_000_000:
                raw_value = raw_value / 1000
            return datetime.fromtimestamp(raw_value).date()

        text = str(raw_value).strip()
        if text.isdigit():
            return MultiUserOptionStrategy.parse_expiry_date(int(text))

        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d-%b-%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
        return None

    def nearest_expiry_info(self, chain_data):
        expiry_rows = chain_data.get("expiryData") or chain_data.get("expirydata") or []
        parsed_expiries = []
        for row in expiry_rows:
            if isinstance(row, dict):
                parsed = (
                    self.parse_expiry_date(row.get("date"))
                    or self.parse_expiry_date(row.get("expiry"))
                    or self.parse_expiry_date(row.get("expiryDate"))
                )
                timestamp = row.get("expiry")
            else:
                parsed = self.parse_expiry_date(row)
                timestamp = row
            if parsed:
                parsed_expiries.append((parsed, timestamp))

        if not parsed_expiries:
            return None, None

        today = datetime.now().date()
        future_expiries = sorted(
            (expiry for expiry in parsed_expiries if expiry[0] >= today),
            key=lambda expiry: expiry[0],
        )
        return future_expiries[0] if future_expiries else sorted(parsed_expiries)[-1]

    def is_expiry_day(self):
        try:
            chain = self.market_fyers.optionchain({"symbol": self.config.index_symbol, "strikecount": 1})
            expiry, expiry_timestamp = self.nearest_expiry_info(chain["data"])
        except Exception as e:
            print("Expiry check error:", e)
            return False

        today = datetime.now().date()
        if expiry is None:
            print("Expiry date not found. Algo stopped.")
            return False
        if expiry != today:
            print(f"Today is {today}; nearest expiry is {expiry}. Algo stopped.")
            return False

        print(f"Expiry day confirmed: {expiry}")
        self.current_expiry_date = expiry
        self.current_expiry_timestamp = expiry_timestamp
        return True

    @staticmethod
    def oi_change_lakhs(option_row):
        raw_value = None
        for key in ("oich", "oi_chng", "oi_change", "oiChange", "changeinOpenInterest"):
            if option_row.get(key) not in (None, ""):
                raw_value = option_row.get(key)
                break

        if raw_value in (None, ""):
            oi = option_row.get("oi")
            prev_oi = option_row.get("prev_oi") or option_row.get("prevOi")
            if oi not in (None, "") and prev_oi not in (None, ""):
                raw_value = float(oi) - float(prev_oi)

        if raw_value in (None, ""):
            return ""

        return round(float(raw_value) / 100000, 2)

    def fetch_option_symbols(self, atm):
        ce = pe = None
        ce_ltp = pe_ltp = None
        ce_oi = pe_oi = ""
        ce_lot = pe_lot = self.config.default_lot_size

        payload = {"symbol": self.config.index_symbol, "strikecount": 2}
        if self.current_expiry_timestamp:
            payload["timestamp"] = str(self.current_expiry_timestamp)

        chain = self.market_fyers.optionchain(payload)
        for opt in chain["data"]["optionsChain"]:
            if float(opt.get("strike_price", 0)) != float(atm):
                continue
            lot_size = int(float(opt.get("lot_size") or opt.get("minLotSize") or self.config.default_lot_size))
            if opt.get("option_type") == "CE":
                ce = opt["symbol"]
                ce_ltp = opt.get("ltp")
                ce_oi = self.oi_change_lakhs(opt)
                ce_lot = lot_size
            elif opt.get("option_type") == "PE":
                pe = opt["symbol"]
                pe_ltp = opt.get("ltp")
                pe_oi = self.oi_change_lakhs(opt)
                pe_lot = lot_size

        return ce, pe, ce_ltp, pe_ltp, ce_oi, pe_oi, ce_lot, pe_lot

    def refresh_entry_oi_change(self):
        try:
            latest = self.fetch_option_symbols(self.current_atm)
        except Exception as e:
            print("OI change refresh error:", e)
            return

        latest_ce, latest_pe, _, _, latest_ce_oi, latest_pe_oi, _, _ = latest
        if self.same_symbol(latest_ce, self.ce_symbol):
            self.ce_oi_chng = latest_ce_oi
        if self.same_symbol(latest_pe, self.pe_symbol):
            self.pe_oi_chng = latest_pe_oi

    def ensure_trade_sheet(self):
        path = Path(self.config.trades_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            with path.open(mode="r", newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                if reader.fieldnames == CSV_COLUMNS:
                    return
            with path.open(mode="w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            return

        with path.open(mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(CSV_COLUMNS)

    def write_trade_rows(self, rows):
        self.ensure_trade_sheet()
        with open(self.config.trades_file, mode="a", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
            writer.writerows([{column: row[column] for column in CSV_COLUMNS} for row in rows])

    def update_trade_row(self, trade, exit_price, result):
        self.ensure_trade_sheet()
        with open(self.config.trades_file, mode="r", newline="") as file:
            rows = list(csv.DictReader(file))

        for row in rows:
            same_trade = (
                row["time"] == trade["time"]
                and row["strike price"] == str(trade["strike price"])
                and row["ce/pe"] == trade["ce/pe"]
                and row["entry"] == str(trade["entry"])
                and row["exit"] == ""
            )
            if same_trade:
                row["exit"] = exit_price
                row["result"] = result
                break

        with open(self.config.trades_file, mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def symbol_code(symbol):
        if not symbol:
            return ""
        return str(symbol).split(":")[-1]

    @classmethod
    def same_symbol(cls, left, right):
        if not left or not right:
            return False
        return str(left) == str(right) or cls.symbol_code(left) == cls.symbol_code(right)

    def has_open_trade(self, symbol):
        return any(trade["is_open"] and self.same_symbol(trade["symbol"], symbol) for trade in self.open_trades)

    def is_scanner_symbol(self, symbol):
        return (
            self.same_symbol(symbol, self.config.index_symbol)
            or self.same_symbol(symbol, self.ce_symbol)
            or self.same_symbol(symbol, self.pe_symbol)
        )

    def canonical_symbol(self, symbol):
        if self.same_symbol(symbol, self.config.index_symbol):
            return self.config.index_symbol
        if self.same_symbol(symbol, self.ce_symbol):
            return self.ce_symbol
        if self.same_symbol(symbol, self.pe_symbol):
            return self.pe_symbol
        for trade in self.open_trades:
            if self.same_symbol(symbol, trade["symbol"]):
                return trade["symbol"]
        return symbol

    def subscribe_symbols(self, symbols):
        symbols_to_add = [symbol for symbol in symbols if symbol and symbol not in self.active_symbols]
        if not symbols_to_add:
            return
        self.ws.subscribe(symbols=symbols_to_add)
        self.active_symbols.update(symbols_to_add)
        print(f"Subscribed: {', '.join(symbols_to_add)}")

    def unsubscribe_symbols(self, symbols):
        symbols_to_remove = [
            symbol
            for symbol in symbols
            if symbol and symbol in self.active_symbols and not self.has_open_trade(symbol)
        ]
        if not symbols_to_remove:
            return
        self.ws.unsubscribe(symbols=symbols_to_remove)
        for symbol in symbols_to_remove:
            self.active_symbols.discard(symbol)
        print(f"Unsubscribed: {', '.join(symbols_to_remove)}")

    @staticmethod
    def available_capital(fyers):
        response = fyers.funds()
        if str(response.get("s", "")).lower() == "error":
            raise RuntimeError(f"Funds error: {response}")

        candidates = []

        def walk(value: Any):
            if isinstance(value, dict):
                for key, child in value.items():
                    key_lower = str(key).lower()
                    if isinstance(child, (int, float)) and any(
                        token in key_lower for token in ("available", "clear", "cash", "balance", "fund")
                    ):
                        candidates.append(float(child))
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(response)
        if not candidates:
            raise RuntimeError(f"Could not read available capital from funds response: {response}")
        return max(candidates)

    @staticmethod
    def effective_capital(user, available_capital):
        set_capital = float(user.get("capital") or 0)
        return min(set_capital, available_capital)

    @staticmethod
    def per_trade_capital(effective_capital, risk_mode):
        divisor = RISK_DIVISORS.get(str(risk_mode or "").strip().lower())
        if divisor is None:
            raise RuntimeError(f"Invalid risk mode: {risk_mode}")
        return effective_capital / divisor

    @staticmethod
    def quantity_for_capital(per_trade_capital, entry_price, lot_size):
        if entry_price <= 0 or lot_size <= 0:
            return 0
        raw_qty = int(per_trade_capital // entry_price)
        return (raw_qty // lot_size) * lot_size

    @staticmethod
    def round_to_tick(price):
        return round(round(float(price) / PRICE_TICK) * PRICE_TICK, 2)

    def entry_limit_price(self, current_price):
        return self.round_to_tick(float(current_price) + ENTRY_LIMIT_OFFSET)

    @staticmethod
    def target_price(entry_price):
        return MultiUserOptionStrategy.round_to_tick(float(entry_price) * (1 + TARGET / 100))

    @staticmethod
    def stoploss_price(entry_price):
        return MultiUserOptionStrategy.round_to_tick(float(entry_price) * (1 + STOPLOSS / 100))

    @staticmethod
    def stoploss_limit_price(stoploss_trigger):
        limit_price = max(float(stoploss_trigger) - STOPLIMIT_LIMIT_OFFSET, PRICE_TICK)
        return MultiUserOptionStrategy.round_to_tick(limit_price)

    @staticmethod
    def order_payload(symbol, qty, side, order_type=2, limit_price=0, stop_price=0):
        return {
            "symbol": symbol,
            "qty": int(qty),
            "type": int(order_type),
            "side": int(side),
            "productType": "INTRADAY",
            "limitPrice": float(limit_price),
            "stopPrice": float(stop_price),
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }

    def place_entry_order(self, fyers, symbol, qty, limit_price):
        return fyers.place_order(
            self.order_payload(symbol, qty, 1, order_type=ORDER_TYPE_LIMIT, limit_price=limit_price)
        )

    def place_exit_order(self, fyers, symbol, qty):
        return fyers.place_order(self.order_payload(symbol, qty, -1, order_type=ORDER_TYPE_MARKET))

    def place_target_order(self, fyers, symbol, qty, target_price):
        return fyers.place_order(
            self.order_payload(symbol, qty, -1, order_type=ORDER_TYPE_LIMIT, limit_price=target_price)
        )

    def place_stoploss_order(self, fyers, symbol, qty, stoploss_trigger, stoploss_limit):
        return fyers.place_order(
            self.order_payload(
                symbol,
                qty,
                -1,
                order_type=ORDER_TYPE_STOP_LIMIT,
                limit_price=stoploss_limit,
                stop_price=stoploss_trigger,
            )
        )

    def place_order_with_retries(self, label, place_fn):
        response = {}
        for attempt in range(1, PROTECTIVE_ORDER_RETRIES + 1):
            try:
                response = place_fn()
            except Exception as e:
                response = {"s": "error", "message": str(e)}

            if self.order_ok(response) and self.response_id(response):
                if attempt > 1:
                    print(f"{label} accepted on retry {attempt}: {response}")
                return response

            print(f"{label} rejected attempt {attempt}: {response}")

        return response

    def place_protective_orders(self, fyers, symbol, qty, entry_price):
        target_price = self.target_price(entry_price)
        stoploss_trigger = self.stoploss_price(entry_price)
        stoploss_limit = self.stoploss_limit_price(stoploss_trigger)

        target_response = self.place_order_with_retries(
            f"{symbol} target limit order",
            lambda: self.place_target_order(fyers, symbol, qty, target_price),
        )
        stoploss_response = self.place_order_with_retries(
            f"{symbol} stoploss stop-limit order",
            lambda: self.place_stoploss_order(fyers, symbol, qty, stoploss_trigger, stoploss_limit),
        )

        return {
            "target": target_response,
            "stoploss": stoploss_response,
            "target_id": self.response_id(target_response),
            "stoploss_id": self.response_id(stoploss_response),
            "target_price": target_price,
            "stoploss_trigger": stoploss_trigger,
            "stoploss_limit": stoploss_limit,
        }

    def cancel_regular_order(self, fyers, order_id):
        if not order_id:
            return None
        return fyers.cancel_order({"id": order_id})

    def cancel_trade_exit_orders(self, trade, completed_leg=None):
        for leg, id_key in (("target", "target_order_id"), ("stoploss", "stoploss_order_id")):
            if leg == completed_leg:
                continue

            order_id = trade.get(id_key)
            if not order_id:
                continue

            response = self.cancel_regular_order(trade["fyers"], order_id)
            if response is not None and not self.order_ok(response):
                print(f"user {trade['user_id']} {trade['ce/pe']} {leg} cancel warning: {response}")
            else:
                trade[id_key] = ""

    @staticmethod
    def response_id(response):
        if not isinstance(response, dict):
            return ""
        for key in ("id", "order_id", "orderId"):
            if response.get(key):
                return response.get(key)
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("id", "order_id", "orderId"):
                if data.get(key):
                    return data.get(key)
        return ""

    @staticmethod
    def order_ok(response):
        if not isinstance(response, dict):
            return False
        return str(response.get("s", "")).lower() == "ok" or response.get("id")

    @staticmethod
    def response_orders(response):
        if not isinstance(response, dict):
            return []

        for key in ("orderBook", "orderbook", "orders"):
            if isinstance(response.get(key), list):
                return response[key]

        data = response.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("orderBook", "orderbook", "orders"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]

        return []

    @staticmethod
    def same_order_id(order, order_id):
        if not isinstance(order, dict) or not order_id:
            return False
        order_id = str(order_id)
        return any(str(order.get(key, "")) == order_id for key in ("id", "order_id", "orderId", "exchOrdId"))

    @staticmethod
    def order_traded_price(order, fallback_price):
        for key in ("tradedPrice", "avgTradedPrice", "averagePrice", "filledAvgPrice"):
            value = order.get(key)
            if value not in (None, "", 0, 0.0):
                return value
        return fallback_price

    @staticmethod
    def order_is_filled(order, expected_qty):
        status = str(order.get("status") or order.get("orderStatus") or order.get("message") or "").strip().lower()
        if status in {"2", "traded", "filled", "complete", "completed", "executed"}:
            return True

        for key in ("filledQty", "filled_qty", "tradedQty", "traded_qty", "filledqty"):
            value = order.get(key)
            if value in (None, ""):
                continue
            try:
                if int(float(value)) >= int(expected_qty):
                    return True
            except (TypeError, ValueError):
                continue

        return False

    def order_fill_info(self, fyers, order_id, expected_qty):
        if not order_id:
            return False, None, None

        try:
            if hasattr(fyers, "get_orders"):
                response = fyers.get_orders({"id": str(order_id)})
            else:
                response = fyers.orderbook()
        except Exception as e:
            return False, None, {"s": "error", "message": str(e)}

        for order in self.response_orders(response):
            if self.same_order_id(order, order_id):
                return self.order_is_filled(order, expected_qty), order, response

        return False, None, response

    def filled_exit_order(self, trade):
        for leg, result, id_key in (
            ("target", "TP", "target_order_id"),
            ("stoploss", "SL", "stoploss_order_id"),
        ):
            filled, order, response = self.order_fill_info(trade["fyers"], trade.get(id_key), trade["qty"])
            if filled:
                return result, leg, self.order_traded_price(order, trade.get(f"{leg}_price") or trade["entry"])
            if response is not None and not self.order_ok(response):
                print(f"user {trade['user_id']} {trade['ce/pe']} orderbook warning: {response}")

        return None, None, None

    def retry_missing_protective_orders(self, trade):
        if trade.get("target_order_id") and trade.get("stoploss_order_id"):
            return

        now = datetime.now()
        retry_after = trade.get("protective_retry_after")
        if retry_after and now < retry_after:
            return

        trade["protective_retry_after"] = now + timedelta(seconds=5)

        if not trade.get("target_order_id"):
            response = self.place_order_with_retries(
                f"{trade['symbol']} target limit order",
                lambda: self.place_target_order(
                    trade["fyers"],
                    trade["symbol"],
                    trade["qty"],
                    trade["target_price"],
                ),
            )
            if self.order_ok(response):
                trade["target_order_id"] = self.response_id(response)
            else:
                print(f"user {trade['user_id']} {trade['ce/pe']} target order still missing: {response}")

        if not trade.get("stoploss_order_id"):
            response = self.place_order_with_retries(
                f"{trade['symbol']} stoploss stop-limit order",
                lambda: self.place_stoploss_order(
                    trade["fyers"],
                    trade["symbol"],
                    trade["qty"],
                    trade["stoploss_price"],
                    trade["stoploss_limit"],
                ),
            )
            if self.order_ok(response):
                trade["stoploss_order_id"] = self.response_id(response)
            else:
                print(f"user {trade['user_id']} {trade['ce/pe']} stoploss order still missing: {response}")

    def save_and_place_trade_rows(self):
        self.refresh_entry_oi_change()
        trade_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        rows_to_write = []

        for user in self.load_active_users():
            user_label = f"user {user['id']} {user.get('email', '')}".strip()
            fyers = self.fyers_for_user(user)
            try:
                available = self.available_capital(fyers)
                effective = self.effective_capital(user, available)
                per_trade = self.per_trade_capital(effective, user.get("risk_mode"))
            except Exception as e:
                print(f"{user_label}: capital check failed: {e}")
                continue

            ce_limit_price = self.entry_limit_price(self.ce_price)
            pe_limit_price = self.entry_limit_price(self.pe_price)
            ce_qty = self.quantity_for_capital(per_trade, ce_limit_price, self.ce_lot_size)
            pe_qty = self.quantity_for_capital(per_trade, pe_limit_price, self.pe_lot_size)
            if ce_qty <= 0 or pe_qty <= 0:
                print(f"{user_label}: skipped, capital too low for lot size")
                continue

            ce_response = self.place_entry_order(fyers, self.ce_symbol, ce_qty, ce_limit_price)
            if not self.order_ok(ce_response):
                print(f"{user_label}: CE entry rejected CE={ce_response}")
                continue

            pe_response = self.place_entry_order(fyers, self.pe_symbol, pe_qty, pe_limit_price)
            if not self.order_ok(pe_response):
                squareoff_response = self.place_exit_order(fyers, self.ce_symbol, ce_qty)
                print(
                    f"{user_label}: PE entry rejected PE={pe_response}; "
                    f"CE squareoff attempted={squareoff_response}"
                )
                continue

            ce_protective_response = self.place_protective_orders(fyers, self.ce_symbol, ce_qty, ce_limit_price)
            pe_protective_response = self.place_protective_orders(fyers, self.pe_symbol, pe_qty, pe_limit_price)
            ce_protective_ok = bool(
                ce_protective_response["target_id"] and ce_protective_response["stoploss_id"]
            )
            pe_protective_ok = bool(
                pe_protective_response["target_id"] and pe_protective_response["stoploss_id"]
            )
            if not ce_protective_ok or not pe_protective_ok:
                print(
                    f"{user_label}: protective order warning; trade kept valid "
                    f"CE_PROTECT={ce_protective_response} PE_PROTECT={pe_protective_response}"
                )

            trades = [
                {
                    "time": trade_time,
                    "strike price": self.current_atm,
                    "ce/pe": "CE",
                    "oi chng": self.ce_oi_chng,
                    "entry": ce_limit_price,
                    "exit": "",
                    "result": "OPEN",
                    "symbol": self.ce_symbol,
                    "qty": ce_qty,
                    "user_id": user["id"],
                    "fyers": fyers,
                    "entry_order_id": self.response_id(ce_response),
                    "target_order_id": ce_protective_response["target_id"],
                    "stoploss_order_id": ce_protective_response["stoploss_id"],
                    "target_price": ce_protective_response["target_price"],
                    "stoploss_price": ce_protective_response["stoploss_trigger"],
                    "stoploss_limit": ce_protective_response["stoploss_limit"],
                    "is_open": True,
                },
                {
                    "time": trade_time,
                    "strike price": self.current_atm,
                    "ce/pe": "PE",
                    "oi chng": self.pe_oi_chng,
                    "entry": pe_limit_price,
                    "exit": "",
                    "result": "OPEN",
                    "symbol": self.pe_symbol,
                    "qty": pe_qty,
                    "user_id": user["id"],
                    "fyers": fyers,
                    "entry_order_id": self.response_id(pe_response),
                    "target_order_id": pe_protective_response["target_id"],
                    "stoploss_order_id": pe_protective_response["stoploss_id"],
                    "target_price": pe_protective_response["target_price"],
                    "stoploss_price": pe_protective_response["stoploss_trigger"],
                    "stoploss_limit": pe_protective_response["stoploss_limit"],
                    "is_open": True,
                },
            ]
            self.open_trades.extend(trades)
            rows_to_write.extend(trades)
            print(
                f"{user_label}: limit entries placed "
                f"CE qty {ce_qty} @ {ce_limit_price}, PE qty {pe_qty} @ {pe_limit_price}"
            )

        if rows_to_write:
            self.write_trade_rows(rows_to_write)
            self.subscribe_symbols([self.ce_symbol, self.pe_symbol])
            print(f"Saved trade rows to {self.config.trades_file}")
        else:
            print("Condition met, but no eligible user orders were placed.")
        return len(rows_to_write)

    def stop_algo(self, reason):
        if self.algo_stopped:
            return
        self.algo_stopped = True
        print(reason)
        try:
            self.ws.close_connection()
        except Exception as e:
            print("WebSocket close error:", e)

    def check_and_trade(self):
        if self.algo_stopped or self.scan_stopped:
            return

        now = datetime.now().time()
        if now < ENTRY_START:
            return
        if now >= SCAN_STOP:
            self.scan_stopped = True
            if not self.open_trades:
                self.stop_algo("No trade before 14:50. Algo stopped.")
            else:
                print("14:50 reached. Scanning stopped; monitoring open trades.")
            return

        if self.spot_price is None or self.ce_price is None or self.pe_price is None or self.current_atm is None:
            return

        diff = abs(float(self.ce_price) - float(self.pe_price))
        diff_min_ok = True if self.config.price_diff_min is None else diff > self.config.price_diff_min
        condition_met = diff_min_ok and diff < self.config.price_diff_max and self.spot_condition(self.spot_price, self.current_atm)
        if not condition_met:
            return

        print("TRADE CONDITION MET")
        print(
            f"Spot {self.spot_price} | Strike {self.current_atm} | "
            f"CE {self.ce_price} | PE {self.pe_price} | CE-PE {round(diff, 2)}"
        )
        self.scan_stopped = True
        placed_rows = self.save_and_place_trade_rows()
        if placed_rows == 0:
            self.stop_algo("No user orders placed. Algo stopped.")

    def monitor_open_trades(self, symbol):
        if self.algo_stopped or symbol not in self.last_prices:
            return

        current = self.last_prices[symbol]
        force_exit = datetime.now().time() >= MONITOR_STOP

        for trade in self.open_trades:
            if not trade["is_open"] or not self.same_symbol(trade["symbol"], symbol):
                continue

            entry = float(trade["entry"])
            pnl = ((float(current) - entry) / entry) * 100
            self.retry_missing_protective_orders(trade)
            filled_result, filled_leg, filled_price = self.filled_exit_order(trade)
            result = None
            exit_price = current
            if filled_result:
                result = filled_result
                exit_price = filled_price
                self.cancel_trade_exit_orders(trade, completed_leg=filled_leg)
            elif force_exit:
                result = "TIME_EXIT"
            elif pnl >= TARGET:
                result = "TP"
            elif pnl <= STOPLOSS:
                result = "SL"

            if not result:
                continue

            if result == "TIME_EXIT":
                self.cancel_trade_exit_orders(trade)
                response = self.place_exit_order(trade["fyers"], trade["symbol"], trade["qty"])
                if not self.order_ok(response):
                    print(f"user {trade['user_id']} {trade['ce/pe']} time exit rejected: {response}")
                    continue
            elif not filled_result:
                if result == "TP" and not trade.get("target_order_id"):
                    response = self.place_order_with_retries(
                        f"{trade['symbol']} target limit order",
                        lambda: self.place_target_order(
                            trade["fyers"],
                            trade["symbol"],
                            trade["qty"],
                            trade["target_price"],
                        ),
                    )
                    if self.order_ok(response):
                        trade["target_order_id"] = self.response_id(response)
                    else:
                        print(f"user {trade['user_id']} {trade['ce/pe']} target fallback to market: {response}")
                        self.cancel_trade_exit_orders(trade)
                        response = self.place_exit_order(trade["fyers"], trade["symbol"], trade["qty"])
                        if not self.order_ok(response):
                            print(f"user {trade['user_id']} {trade['ce/pe']} target exit rejected: {response}")
                            continue
                        exit_price = current
                        filled_result = result

                if result == "SL" and not trade.get("stoploss_order_id"):
                    response = self.place_order_with_retries(
                        f"{trade['symbol']} stoploss stop-limit order",
                        lambda: self.place_stoploss_order(
                            trade["fyers"],
                            trade["symbol"],
                            trade["qty"],
                            trade["stoploss_price"],
                            trade["stoploss_limit"],
                        ),
                    )
                    if self.order_ok(response):
                        trade["stoploss_order_id"] = self.response_id(response)
                    else:
                        print(f"user {trade['user_id']} {trade['ce/pe']} stoploss fallback to market: {response}")
                        self.cancel_trade_exit_orders(trade)
                        response = self.place_exit_order(trade["fyers"], trade["symbol"], trade["qty"])
                        if not self.order_ok(response):
                            print(f"user {trade['user_id']} {trade['ce/pe']} stoploss exit rejected: {response}")
                            continue
                        exit_price = current
                        filled_result = result

                if not filled_result:
                    filled_result, filled_leg, filled_price = self.filled_exit_order(trade)
                    if not filled_result:
                        continue
                    result = filled_result
                    exit_price = filled_price
                    self.cancel_trade_exit_orders(trade, completed_leg=filled_leg)

            trade["is_open"] = False
            trade["exit"] = exit_price
            trade["result"] = result
            self.update_trade_row(trade, exit_price, result)
            print(
                f"user {trade['user_id']} {trade['ce/pe']} {result} | "
                f"Strike {trade['strike price']} | Entry {entry} | Exit {exit_price}"
            )

        if not self.has_open_trade(symbol) and not self.is_scanner_symbol(symbol):
            self.unsubscribe_symbols([symbol])

        if self.scan_stopped and self.open_trades and all(not trade["is_open"] for trade in self.open_trades):
            self.stop_algo("All trades closed. Algo stopped.")

    def on_message(self, msg):
        if self.algo_stopped:
            return

        raw_symbol = msg.get("symbol")
        ltp = msg.get("ltp")
        if not raw_symbol or ltp is None:
            return

        symbol = self.canonical_symbol(raw_symbol)
        self.last_prices[symbol] = ltp

        if symbol == self.config.index_symbol:
            self.spot_price = float(ltp)
            if not self.scan_stopped:
                self.update_atm_subscriptions()
        elif self.same_symbol(symbol, self.ce_symbol):
            self.ce_price = float(ltp)
        elif self.same_symbol(symbol, self.pe_symbol):
            self.pe_price = float(ltp)

        self.monitor_open_trades(symbol)
        self.check_and_trade()

    def update_atm_subscriptions(self):
        new_atm = self.get_atm(self.spot_price)
        if new_atm == self.current_atm:
            return

        old_ce = self.ce_symbol
        old_pe = self.pe_symbol
        self.current_atm = new_atm
        self.ce_price = None
        self.pe_price = None
        self.ce_oi_chng = ""
        self.pe_oi_chng = ""

        try:
            self.unsubscribe_symbols([old_ce, old_pe])
        except Exception as e:
            print("Unsubscribe error:", e)

        try:
            option_data = self.fetch_option_symbols(self.current_atm)
        except Exception as e:
            print("Fetch error:", e)
            return

        new_ce, new_pe, new_ce_ltp, new_pe_ltp, new_ce_oi, new_pe_oi, new_ce_lot, new_pe_lot = option_data
        if not new_ce or not new_pe:
            print("Invalid CE/PE, skipping...")
            return

        self.ce_symbol = new_ce
        self.pe_symbol = new_pe
        self.ce_price = new_ce_ltp
        self.pe_price = new_pe_ltp
        self.ce_oi_chng = new_ce_oi
        self.pe_oi_chng = new_pe_oi
        self.ce_lot_size = new_ce_lot
        self.pe_lot_size = new_pe_lot

        try:
            self.subscribe_symbols([self.ce_symbol, self.pe_symbol])
        except Exception as e:
            print("Subscribe error:", e)

        print(f"ATM updated: {self.current_atm}")

    def on_open(self):
        print("WebSocket Connected")
        self.ensure_trade_sheet()
        self.subscribe_symbols([self.config.index_symbol])

    def run(self):
        if not self.is_expiry_day():
            return
        self.ws = data_ws.FyersDataSocket(
            access_token=self.market_user["broker_session_token"],
            on_connect=self.on_open,
            on_message=self.on_message,
            log_path="",
        )
        self.ws.connect()


def run_strategy(config: StrategyConfig):
    MultiUserOptionStrategy(config).run()

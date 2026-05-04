from pathlib import Path

try:
    from .common import StrategyConfig, run_strategy
except ImportError:
    from common import StrategyConfig, run_strategy


BASE_DIR = Path(__file__).resolve().parent

CONFIG = StrategyConfig(
    name="nifty",
    index_name="Nifty",
    index_symbol="NSE:NIFTY50-INDEX",
    strike_step=50,
    price_diff_min=None,
    price_diff_max=15,
    spot_offset=7,
    tolerance=0.75,
    default_lot_size=65,
    trades_file=str(BASE_DIR / "nifty_trades.csv"),
)


if __name__ == "__main__":
    run_strategy(CONFIG)

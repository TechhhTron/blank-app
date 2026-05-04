from pathlib import Path

try:
    from .common import StrategyConfig, run_strategy
except ImportError:
    from common import StrategyConfig, run_strategy


BASE_DIR = Path(__file__).resolve().parent

CONFIG = StrategyConfig(
    name="sensex",
    index_name="Sensex",
    index_symbol="BSE:SENSEX-INDEX",
    strike_step=100,
    price_diff_min=7,
    price_diff_max=19,
    spot_offset=4,
    tolerance=0.75,
    default_lot_size=20,
    trades_file=str(BASE_DIR / "sensex_trades.csv"),
)


if __name__ == "__main__":
    run_strategy(CONFIG)

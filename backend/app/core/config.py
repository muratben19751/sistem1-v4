import os
from types import SimpleNamespace
from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name) or fallback)
    except ValueError:
        return fallback


def _int(name: str, fallback: int) -> int:
    try:
        return int(os.environ.get(name) or fallback)
    except ValueError:
        return fallback


is_production = os.environ.get("APP_ENV") == "production"

config = SimpleNamespace(
    port=_int("PORT", 3500),
    host=os.environ.get("HOST") or ("0.0.0.0" if is_production else "127.0.0.1"),
    auth_token=os.environ.get("AUTH_TOKEN") or "dev-token",
    auth_token_min_length=_int("AUTH_TOKEN_MIN_LENGTH", 24),
    cors_origin=os.environ.get("CORS_ORIGIN") or "http://localhost:5200",
    background=SimpleNamespace(
        price_updater=_bool_env("ENABLE_PRICE_UPDATER", True),
        auto_start_bots=_bool_env("AUTO_START_BOTS", False),
        delist_checker=_bool_env("AUTO_START_DELIST_CHECKER", False),
        telegram_client=_bool_env("AUTO_START_TELEGRAM_CLIENT", False),
        reparse_old_alerts=_bool_env("AUTO_REPARSE_OLD_ALERTS", False),
        optimizer=_bool_env("AUTO_START_OPTIMIZER", False),
        # Optimizer GA dongusu server icinde mi kossun? false -> ayri process (optimizer_main.py)
        # kosar (Windows'ta ProcessPool spawn icin gerekli). Server yine /start /stop /status servis eder.
        optimizer_in_server=_bool_env("OPTIMIZER_IN_SERVER", True),
        replicas=_bool_env("AUTO_START_REPLICAS", False),
        replica_compare=_bool_env("AUTO_START_REPLICA_COMPARE", False),
        replica_tuner=_bool_env("AUTO_START_REPLICA_TUNER", False),
    ),
    paper=SimpleNamespace(
        initial_balance=_float("PAPER_INITIAL_BALANCE", 10000),
        slippage=_float("PAPER_SLIPPAGE", 0.05),
        maker_fee=_float("PAPER_MAKER_FEE", 0.02),
        taker_fee=_float("PAPER_TAKER_FEE", 0.055),
    ),
    bybit=SimpleNamespace(
        api_key=os.environ.get("BYBIT_API_KEY") or "",
        api_secret=os.environ.get("BYBIT_API_SECRET") or "",
        rate_limit_delay_ms=_int("BYBIT_RATE_LIMIT_DELAY_MS", 150),
    ),
    anthropic=SimpleNamespace(
        api_key=os.environ.get("ANTHROPIC_API_KEY") or "",
    ),
    telegram=SimpleNamespace(
        api_id=os.environ.get("TELEGRAM_API_ID") or "",
        api_hash=os.environ.get("TELEGRAM_API_HASH") or "",
        session_string=os.environ.get("TELEGRAM_SESSION_STRING") or "",
        channels=SimpleNamespace(
            sniper=os.environ.get("TELEGRAM_CHANNEL_SNIPER") or "",
            hammer=os.environ.get("TELEGRAM_CHANNEL_HAMMER") or "",
            fr=os.environ.get("TELEGRAM_CHANNEL_FR") or "",
            m1a=os.environ.get("TELEGRAM_CHANNEL_M1A") or "",
        ),
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or "",
        forward_to=os.environ.get("TELEGRAM_FORWARD_TO") or "",
        notify_bot_token=os.environ.get("TELEGRAM_NOTIFY_BOT_TOKEN") or "",
        notify_chat_id=os.environ.get("TELEGRAM_NOTIFY_CHAT_ID") or "",
    ),
)

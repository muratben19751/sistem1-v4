import math
import re

from ..core.logger import create_logger

log = create_logger("alert-parser")

STAR_REGEX = re.compile("⭐️?")
SYMBOL_REGEX = re.compile(r"(?:^|[^A-Z0-9])#?\$?([A-Z0-9]{1,})(?:[\/._-]?USDT)\b", re.IGNORECASE)
DIRECTION_REGEX = re.compile(r"\b(UP|DOWN|LONG|SHORT|BUY|SELL)\b", re.IGNORECASE)
SIGNAL_TYPE_REGEX = re.compile(
    r"Strategy[:\s]*([^\n\r]+?)(?=\s+(?:Boost\s*Value|Drop\s*Value|Current\s*Price|Previous\s*Price|RSI|SRSI)\b|$)",
    re.IGNORECASE,
)
BOOST_REGEX = re.compile(r"(?:Boost|Drop)\s*Value[:\s]*([+-]?[0-9.]+)%?", re.IGNORECASE)
CURRENT_PRICE_REGEX = re.compile(r"Current\s*Price[:\s]*([0-9.]+)", re.IGNORECASE)
PREVIOUS_PRICE_REGEX = re.compile(r"Previous\s*Price[:\s]*([0-9.]+)", re.IGNORECASE)
PRICE_FALLBACK_REGEX = re.compile(r"(?:Price|Fiyat|@)[:\s]*\$?([0-9.]+)", re.IGNORECASE)
STRATEGY_PRESENT_REGEX = re.compile(r"Strategy[:\s]", re.IGNORECASE)
EMOJI_DOWN = re.compile("\U0001F534")
EMOJI_UP = re.compile("\U0001F7E2")

FR_VALUE_REGEX = re.compile(r"\b(?:Funding\s*Rate|Funding|FR)\b[:\s]*([+-]?[0-9.]+)", re.IGNORECASE)
FR_PREVIOUS_REGEX = re.compile(r"Previous\s*Funding[:\s]*([+-]?[0-9.]+)", re.IGNORECASE)
FR_TIME_REGEX = re.compile(r"(?:Time\s*Remaining|Time)[:\s]*(\d{1,2}:\d{2}:\d{2})", re.IGNORECASE)
FR_CHANGED_REGEX = re.compile(r"Funding\s+changed\s+from\s+([+-])\s+to\s+([+-])", re.IGNORECASE)
FR_NEUTRAL_BAND = 0.005

_LOCAL_SUFFIX_REGEX = re.compile(r"_local$")
_CLEAN_STARS_REGEX = re.compile(r"\*+")
_CLEAN_JUNK_REGEX = re.compile(r"[^\w\s.|:,]", re.ASCII)
_TIMEFRAME_REGEX = re.compile(
    r"\b(1m|5m|15m|1h|4h|1d|\d+[mhd])\s*[:.=]\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_RSI_MARKER = re.compile(r"(?:^|\s)RSI\s*[:：]", re.IGNORECASE)
_SRSI_MARKER = re.compile(r"(?:^|\s)SRSI\s*[:：]", re.IGNORECASE)
_RSI_NEXT_LABEL = re.compile(
    r"(?:^|\s)(?:SRSI|Stochastic|BTC\s*Status|Binance|Bybit|TradingView|Funding|Time\s*Remaining|Volume|Strategy)\b",
    re.IGNORECASE,
)
_SRSI_NEXT_LABEL = re.compile(
    r"(?:^|\s)(?:RSI|Stochastic|BTC\s*Status|Binance|Bybit|TradingView|Funding|Time\s*Remaining|Volume|Strategy)\b",
    re.IGNORECASE,
)
_HAMMER_1M_REGEX = re.compile(r"RSI[:\s].*1m\s*[:.=]", re.IGNORECASE | re.DOTALL)
_HAMMER_5M_REGEX = re.compile(r"RSI[:\s].*5m\s*[:.=]", re.IGNORECASE | re.DOTALL)

_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _parse_float(text) -> float:
    if text is None:
        return float("nan")
    m = _FLOAT_RE.match(str(text).strip())
    if not m:
        return float("nan")
    try:
        return float(m.group(0))
    except ValueError:
        return float("nan")


def _to_number(val: float):
    if val == int(val):
        return int(val)
    return val


def parse_timeframe_values(line: str) -> dict:
    result: dict = {}
    cleaned = _CLEAN_JUNK_REGEX.sub("", _CLEAN_STARS_REGEX.sub("", line)).strip()
    for m in _TIMEFRAME_REGEX.finditer(cleaned):
        val = _parse_float(m.group(2))
        if not math.isnan(val):
            result[m.group(1).lower()] = _to_number(val)
    return result


def extract_metric_values(raw_message: str, label: str) -> str | None:
    marker = _RSI_MARKER if label == "RSI" else _SRSI_MARKER
    match = marker.search(raw_message)
    if not match:
        return None

    start = match.start() + len(match.group(0))
    rest = raw_message[start:]
    next_label = _RSI_NEXT_LABEL if label == "RSI" else _SRSI_NEXT_LABEL
    nxt = next_label.search(rest)
    if nxt is not None:
        return rest[: nxt.start()].strip()
    return rest.strip()


def detect_source_type(raw_message: str, source: str | None = None) -> str:
    s = _LOCAL_SUFFIX_REGEX.sub("", source or "")
    if s == "fr":
        return "fr"
    if s in ("m1_a", "m1a"):
        return "m1_a"
    if s in ("v3_a", "v3a"):
        return "v3_a"
    if s in ("4s_sniper", "sniper", "nw"):
        return "4s_sniper"
    if s == "hammer":
        return "hammer"
    if STRATEGY_PRESENT_REGEX.search(raw_message):
        return "4s_sniper"
    if _HAMMER_1M_REGEX.search(raw_message) or _HAMMER_5M_REGEX.search(raw_message):
        return "hammer"
    return "unknown"


def extract_explicit_direction(raw_message: str) -> str | None:
    if EMOJI_DOWN.search(raw_message):
        return "DOWN"
    if EMOJI_UP.search(raw_message):
        return "UP"
    dir_match = DIRECTION_REGEX.search(raw_message)
    if not dir_match:
        return None
    d = dir_match.group(1).upper()
    return "DOWN" if d in ("DOWN", "SHORT", "SELL") else "UP"


def derive_fr_direction(funding_rate_pct: float | None) -> str | None:
    if funding_rate_pct is None or not math.isfinite(funding_rate_pct):
        return None
    if funding_rate_pct <= -FR_NEUTRAL_BAND:
        return "UP"
    if funding_rate_pct >= FR_NEUTRAL_BAND:
        return "DOWN"
    return None


def _has_derivable_fr_direction(raw_message: str, source: str = "telegram") -> bool:
    if detect_source_type(raw_message, source) != "fr":
        return False
    fr_match = FR_VALUE_REGEX.search(raw_message)
    if not fr_match:
        return False
    return derive_fr_direction(_parse_float(fr_match.group(1))) is not None


def get_alert_parse_failure_reason(raw_message: str, source: str = "telegram") -> str:
    if not raw_message or len(raw_message.strip()) == 0:
        return "empty_message"
    if not SYMBOL_REGEX.search(raw_message):
        return "symbol_not_found"
    if not extract_explicit_direction(raw_message) and not _has_derivable_fr_direction(raw_message, source):
        return "direction_not_found"
    return "unknown_format"


def parse_alert(raw_message: str, source: str = "telegram") -> dict | None:
    symbol_match = SYMBOL_REGEX.search(raw_message)
    if not symbol_match:
        return None

    symbol = f"{symbol_match.group(1).upper()}USDT"
    source_type = detect_source_type(raw_message, source)
    explicit_direction = extract_explicit_direction(raw_message)

    strategy_match = SIGNAL_TYPE_REGEX.search(raw_message)
    signal_type = strategy_match.group(1).strip() if strategy_match else "UNKNOWN"

    rsi: dict = {}
    srsi: dict = {}

    rsi_values = extract_metric_values(raw_message, "RSI")
    if rsi_values:
        rsi = parse_timeframe_values(rsi_values)

    srsi_values = extract_metric_values(raw_message, "SRSI")
    if srsi_values:
        srsi = parse_timeframe_values(srsi_values)

    boost_match = BOOST_REGEX.search(raw_message)
    current_price_match = CURRENT_PRICE_REGEX.search(raw_message)
    previous_price_match = PREVIOUS_PRICE_REGEX.search(raw_message)
    price_fallback = PRICE_FALLBACK_REGEX.search(raw_message)

    funding_rate: float | None = None
    previous_funding: float | None = None
    time_remaining: str | None = None
    funding_changed = 0

    if source_type == "fr":
        fr_match = FR_VALUE_REGEX.search(raw_message)
        if fr_match:
            funding_rate = _parse_float(fr_match.group(1))

        prev_fr_match = FR_PREVIOUS_REGEX.search(raw_message)
        if prev_fr_match:
            previous_funding = _parse_float(prev_fr_match.group(1))

        time_match = FR_TIME_REGEX.search(raw_message)
        if time_match:
            time_remaining = time_match.group(1)

        changed_match = FR_CHANGED_REGEX.search(raw_message)
        if changed_match:
            funding_changed = 1

        if signal_type == "UNKNOWN":
            if changed_match:
                from_sign = changed_match.group(1)
                to_sign = changed_match.group(2)
                signal_type = f"FR_CHANGE_{'P' if from_sign == '+' else 'N'}_TO_{'P' if to_sign == '+' else 'N'}"
            elif fr_match:
                signal_type = "FR_UPDATE"

    direction = explicit_direction if explicit_direction is not None else (
        derive_fr_direction(funding_rate) if source_type == "fr" else None
    )
    if not direction:
        return None

    star_matches = STAR_REGEX.findall(raw_message)
    stars = len(star_matches) if star_matches else 0

    return {
        "symbol": symbol,
        "direction": direction,
        "signalType": signal_type,
        "sourceType": source_type,
        "rsi": rsi,
        "srsi": srsi,
        "boostValue": _parse_float(boost_match.group(1)) if boost_match else None,
        "price": (
            _parse_float(current_price_match.group(1)) if current_price_match
            else (_parse_float(price_fallback.group(1)) if price_fallback else None)
        ),
        "previousPrice": _parse_float(previous_price_match.group(1)) if previous_price_match else None,
        "fundingRate": funding_rate,
        "previousFunding": previous_funding,
        "timeRemaining": time_remaining,
        "fundingChanged": funding_changed,
        "stars": stars,
        "rawMessage": raw_message,
        "source": source,
    }

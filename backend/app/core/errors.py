import traceback

from .logger import create_logger

log = create_logger("api-error")

# Kullaniciya oldugu gibi gosterilebilir hata tipleri (girdi/dogrulama kaynakli).
_SAFE_TYPES = (ValueError, PermissionError, TimeoutError)


def public_error(err: Exception, context: str, fallback: str = "Internal error") -> str:
    """500 yanitlari icin guvenli mesaj: domain hatalari (Bybit API, dogrulama)
    oldugu gibi gecer; ic hatalar (SQL, dosya yolu, stack) generic mesaja duser.
    Tam detay her durumda loga yazilir."""
    msg = str(err)
    log.error(f"{context}: {type(err).__name__}: {msg}\n{traceback.format_exc()}")
    if isinstance(err, _SAFE_TYPES) or msg.startswith("Bybit API error"):
        return msg or fallback
    return fallback

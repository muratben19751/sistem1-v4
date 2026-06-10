import sys
from datetime import datetime, timezone

# Windows + pm2 altinda stdout/stderr cp1254 olabiliyor; emoji iceren log (orn. telegram
# alarmlari 🟢🔴) UnicodeEncodeError verip CAGIRANI cokertiyordu. UTF-8'e ayarla (best-effort).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def _ts() -> str:
    now = datetime.now(timezone.utc)  # saati bir kez ornekle (saniye/ms tutarli olsun)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Logger:
    def __init__(self, name: str):
        self.name = name

    def _emit(self, level: str, message: str, extra=None) -> None:
        line = f"[{_ts()}] [{level}] [{self.name}] {message}"
        if extra:
            line += f" {extra}"
        stream = sys.stderr if level in ("ERROR", "WARN") else sys.stdout
        try:
            print(line, file=stream, flush=True)
        except UnicodeEncodeError:
            enc = getattr(stream, "encoding", None) or "ascii"
            print(line.encode(enc, "replace").decode(enc, "replace"), file=stream, flush=True)

    def info(self, message: str, extra=None) -> None:
        self._emit("INFO", message, extra)

    def warn(self, message: str, extra=None) -> None:
        self._emit("WARN", message, extra)

    def error(self, message: str, extra=None) -> None:
        self._emit("ERROR", message, extra)

    def debug(self, message: str, extra=None) -> None:
        self._emit("DEBUG", message, extra)


def create_logger(name: str) -> Logger:
    return Logger(name)

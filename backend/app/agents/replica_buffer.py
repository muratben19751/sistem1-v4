MAX_PER_CHANNEL = 2000

_buffers: dict[str, list[dict]] = {}
_last_emit: dict[str, float] = {}
_last_scan: dict[str, float] = {}


def record_replica_signal(sig: dict) -> None:
    channel = sig["channel"]
    b = _buffers.get(channel)
    if b is None:
        b = []
        _buffers[channel] = b
    b.append(sig)
    if len(b) > MAX_PER_CHANNEL:
        del b[0:len(b) - MAX_PER_CHANNEL]


def get_replica_signals(since_ms: float) -> list[dict]:
    out: list[dict] = []
    for b in _buffers.values():
        for s in b:
            if s["ts"] >= since_ms:
                out.append(s)
    return out


def record_replica_scan(channel: str, completed_at: float) -> None:
    _last_scan[channel] = completed_at


def get_replica_scan_time(channel: str) -> float | None:
    return _last_scan.get(channel)


def cooldown_ok(channel: str, symbol: str, direction: str, cooldown_ms: float, now: float) -> bool:
    # SADECE kontrol et, tuketme. Cooldown ancak alarm gercekten teslim edilince (ingest
    # basarili) commit_cooldown ile yazilir; aksi halde basarisiz bir ingest sembolu bos
    # yere COOLDOWN_MS boyunca susturuyordu.
    if cooldown_ms <= 0:
        return True
    last = _last_emit.get(f"{channel}|{symbol}|{direction}", 0)
    return now - last >= cooldown_ms


def commit_cooldown(channel: str, symbol: str, direction: str, now: float) -> None:
    _last_emit[f"{channel}|{symbol}|{direction}"] = now

import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from ..core.config import config
from ..core.logger import create_logger
from ..core.time import format_db_time_ms, parse_db_time_ms
from ..db.database import query_one
from .telegram_listener import process_incoming_alert

log = create_logger("telegram-client")

_client: TelegramClient | None = None
CHANNEL_MAP: dict[str, str] = {}
_backfill_lock = asyncio.Lock()


def _add_channel_variants(chan_id: str, source: str) -> None:
    CHANNEL_MAP[chan_id] = source
    abs_id = chan_id.lstrip("-")
    CHANNEL_MAP[abs_id] = source
    if abs_id.startswith("100"):
        CHANNEL_MAP[abs_id[3:]] = source
    CHANNEL_MAP[f"-100{abs_id}"] = source
    CHANNEL_MAP[f"-{abs_id}"] = source


def _build_channel_map() -> None:
    ch = config.telegram.channels
    if ch.sniper:
        _add_channel_variants(ch.sniper, "4s_sniper")
    if ch.hammer:
        _add_channel_variants(ch.hammer, "hammer")
    if ch.fr:
        _add_channel_variants(ch.fr, "fr")
    if ch.m1a:
        _add_channel_variants(ch.m1a, "m1_a")


def _find_source(chat_id: str | None, peer_channel_id: str | None) -> str | None:
    keys = [chat_id, peer_channel_id, f"-100{chat_id}", f"-{chat_id}", f"-100{peer_channel_id}", f"-{peer_channel_id}"]
    for key in keys:
        if key and key in CHANNEL_MAP:
            return CHANNEL_MAP[key]
    return None


async def start_telegram_client() -> None:
    global _client
    api_id = config.telegram.api_id
    api_hash = config.telegram.api_hash
    session = config.telegram.session_string
    if not api_id or not api_hash or not session:
        log.info("Telegram client disabled (missing API_ID, API_HASH, or SESSION_STRING)")
        return

    _build_channel_map()
    if not CHANNEL_MAP:
        log.info("Telegram client disabled (no channels configured)")
        return
    log.info(f"Channel map: {CHANNEL_MAP}")

    _client = TelegramClient(StringSession(session), int(api_id), api_hash,
                             connection_retries=None, retry_delay=5, auto_reconnect=True, flood_sleep_threshold=60)

    @_client.on(events.NewMessage)
    async def _handler(event):  # noqa: ANN001
        text = event.message.message if event.message else None
        if not text:
            return
        chat_id = str(event.chat_id) if event.chat_id is not None else None
        peer_channel_id = None
        try:
            peer = getattr(event.message, "peer_id", None)
            peer_channel_id = str(getattr(peer, "channel_id", None)) if peer else None
        except Exception:  # noqa: BLE001
            peer_channel_id = None
        source = _find_source(chat_id, peer_channel_id)
        if not source:
            return
        # Once ISLE (log emoji yuzunden cokerse bile alarm kaydedilsin), sonra logla.
        try:
            process_incoming_alert(text, source)
        except Exception as err:  # noqa: BLE001
            log.error(f"Alert processing error: {err}")
        try:
            log.info(f"[{source}] {text[:80]}")
        except Exception:  # noqa: BLE001
            pass

    try:
        await _client.connect()
        me = await _client.get_me()
        name = getattr(me, "username", None) or getattr(me, "first_name", None) or getattr(me, "id", "?")
        log.info(f"Telegram client connected; logged in as {name}")
        # Kanal entity'lerini onbellege al: entity cozulmeden telethon bazi kanallarin
        # NewMessage guncellemelerini dusurur (yalnizca fr geliyordu). Hepsini prime et.
        ch = config.telegram.channels
        for cid in (ch.sniper, ch.hammer, ch.fr, ch.m1a):
            if not cid:
                continue
            try:
                await _client.get_input_entity(int(cid))
            except Exception as err:  # noqa: BLE001
                log.warn(f"Channel entity resolve failed for {cid}: {err}")
        log.info(f"Listening to channels for: {', '.join(sorted(set(CHANNEL_MAP.values())))}")
        # Client'i acik tut: bg-task'in erken bitmesi yerine baglanti kopana kadar dinle.
        # (connect()+return deseninde guncelleme dongusu sahipligi belirsiz kalip duruyordu.)
        await _client.run_until_disconnected()
    except Exception as err:  # noqa: BLE001
        log.error(f"Telegram client connection failed: {err}")


async def stop_telegram_client() -> None:
    global _client
    if _client is not None:
        try:
            await _client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        _client = None
        log.info("Telegram client disconnected")


async def backfill_channel_history(limit: int = 500) -> list[dict]:
    if _client is None or not _client.is_connected():
        raise RuntimeError("Telegram client not connected")
    ch = config.telegram.channels
    channels = []
    if ch.fr:
        channels.append({"id": ch.fr, "source": "fr"})
    if ch.hammer:
        channels.append({"id": ch.hammer, "source": "hammer"})
    if ch.sniper:
        channels.append({"id": ch.sniper, "source": "4s_sniper"})
    if ch.m1a:
        channels.append({"id": ch.m1a, "source": "m1_a"})

    async with _backfill_lock:
        results = []
        for c in channels:
            fetched = 0
            inserted = 0
            try:
                entity = await _client.get_input_entity(int(c["id"]))
                async for msg in _client.iter_messages(entity, limit=limit):
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    fetched += 1
                    created_at = None
                    if msg.date:
                        raw_created_at = msg.date.astimezone(timezone.utc).isoformat()
                        created_at = format_db_time_ms(parse_db_time_ms(raw_created_at))
                    if created_at and query_one(
                        """
                        SELECT 1 FROM alerts
                        WHERE source = ? AND created_at = ? AND raw_message = ?
                        LIMIT 1
                        """,
                        (c["source"], created_at, text),
                    ):
                        continue
                    try:
                        alert_data = process_incoming_alert(
                            text,
                            c["source"],
                            received_at=created_at,
                        )
                        if alert_data:
                            inserted += 1
                    except Exception:  # noqa: BLE001
                        pass
                log.info(f"Backfill [{c['source']}]: {fetched} fetched, {inserted} inserted")
            except Exception as err:  # noqa: BLE001
                log.error(f"Backfill [{c['source']}] error: {err}")
            results.append({"channel": c["source"], "fetched": fetched, "inserted": inserted})
        return results

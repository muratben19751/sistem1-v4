import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..services.bot_manager import (
    start_bot,
    stop_bot,
    get_bot_status,
    get_all_bot_statuses,
    get_bot_logs,
)
from ..db.database import query_one, query_all

router = APIRouter()

_INT_RE = re.compile(r"^\d+$")
_MAX_SAFE_INTEGER = 9007199254740991


def parse_account_id(raw) -> int | None:
    text = str(raw if raw is not None else "").strip()
    if not _INT_RE.match(text):
        return None
    value = int(text)
    return value if value > 0 else None


def parse_bounded_int(raw, fallback: int, minimum: int, maximum: int) -> int:
    text = str(raw if raw is not None else "").strip()
    if not _INT_RE.match(text):
        return fallback
    value = int(text)
    return min(max(value, minimum), maximum)


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/status")
async def status(request: Request):
    raw_account_id = request.query_params.get("accountId")
    account_id = parse_account_id(raw_account_id) if raw_account_id is not None else None
    if raw_account_id is not None and account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    if account_id is not None:
        return get_bot_status(account_id)
    return {"bots": get_all_bot_statuses()}


@router.post("/start")
async def start(request: Request):
    body = await _read_body(request)
    account_id = parse_account_id(body.get("accountId"))
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "accountId required"})
    result = start_bot(account_id)
    if not result["success"]:
        return JSONResponse(status_code=400, content=result)
    return get_bot_status(account_id)


@router.post("/stop")
async def stop(request: Request):
    body = await _read_body(request)
    account_id = parse_account_id(body.get("accountId"))
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "accountId required"})
    stop_bot(account_id)
    return get_bot_status(account_id)


@router.get("/logs")
async def logs(request: Request):
    account_id = parse_account_id(request.query_params.get("accountId"))
    limit = parse_bounded_int(request.query_params.get("limit"), 50, 1, 10000)
    offset = parse_bounded_int(request.query_params.get("offset"), 0, 0, _MAX_SAFE_INTEGER)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "accountId required"})
    return get_bot_logs(account_id, limit, offset)


@router.get("/logs/count")
async def logs_count(request: Request):
    account_id = parse_account_id(request.query_params.get("accountId"))
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "accountId required"})
    # bot_manager.getBotLogsCount not ported; query DB directly to match v3 shape.
    row = query_one(
        "SELECT COUNT(*) as total, MIN(created_at) as oldest, MAX(created_at) as newest FROM bot_logs WHERE account_id = ?",
        (account_id,),
    )
    return {"total": row["total"], "oldest": row["oldest"], "newest": row["newest"]}


@router.get("/logs/export")
async def logs_export(request: Request):
    account_id = parse_account_id(request.query_params.get("accountId"))
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "accountId required"})
    fname = f"bot-logs-acc{account_id}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"
    # bot_manager.streamBotLogsCsv not ported; build CSV directly to match v3 output.
    parts = ["time,level,message\n"]
    rows = query_all(
        "SELECT created_at, level, message FROM bot_logs WHERE account_id = ? ORDER BY id ASC",
        (account_id,),
    )
    def _csv_safe(v: str) -> str:
        # Formul enjeksiyonu: =,+,-,@ ile baslayan hucreler Excel/Sheets'te formul olarak
        # calisir; basina ' koyarak etkisizlestir (alarm metni bot_logs'a gelebilir).
        return ("'" + v) if v and v[0] in ("=", "+", "-", "@") else v

    for r in rows:
        time = _csv_safe((r["created_at"] or "").replace(",", " "))
        level = _csv_safe((r["level"] or "").replace(",", " "))
        msg = _csv_safe(str(r["message"] or "")).replace('"', '""')
        parts.append(f'{time},{level},"{msg}"\n')
    return Response(
        content="".join(parts),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

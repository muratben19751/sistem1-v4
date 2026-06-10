import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_all, execute

router = APIRouter()

KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _js_string(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@router.get("")
async def get_settings():
    settings = query_all("SELECT * FROM app_config")
    result: dict[str, str] = {}
    for s in settings:
        result[s["key"]] = s["value"]
    return result


@router.put("/{key}")
async def put_setting(key: str, request: Request):
    if not KEY_RE.match(key):
        return JSONResponse(status_code=400, content={"error": "Invalid key"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    value = body.get("value")
    if value is None:
        return JSONResponse(status_code=400, content={"error": "value required"})
    value_str = _js_string(value)
    if len(value_str) > 5000:
        return JSONResponse(status_code=400, content={"error": "value too long"})
    execute(
        """
        INSERT INTO app_config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        (key, value_str),
    )
    return {"success": True}

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_all, execute

router = APIRouter()


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


@router.get("")
async def list_labels():
    rows = query_all("SELECT * FROM rule_labels")
    return [dict(r) for r in rows]


@router.put("/{key}")
async def upsert_label(key: str, request: Request):
    if not key or not isinstance(key, str) or len(key) == 0 or len(key) > 100:
        return JSONResponse(status_code=400, content={"error": "invalid key"})
    body = await _read_body(request)
    custom_name = body.get("custom_name")
    custom_note = body.get("custom_note")
    if custom_name is not None and (not isinstance(custom_name, str) or len(custom_name) > 80):
        return JSONResponse(status_code=400, content={"error": "invalid custom_name"})
    if custom_note is not None and (not isinstance(custom_note, str) or len(custom_note) > 300):
        return JSONResponse(status_code=400, content={"error": "invalid custom_note"})

    name = custom_name.strip() if isinstance(custom_name, str) and len(custom_name.strip()) > 0 else None
    note = custom_note.strip() if isinstance(custom_note, str) and len(custom_note.strip()) > 0 else None

    execute(
        """
    INSERT INTO rule_labels (rule_key, custom_name, custom_note, updated_at)
    VALUES (?, ?, ?, datetime('now'))
    ON CONFLICT(rule_key) DO UPDATE SET
      custom_name = excluded.custom_name,
      custom_note = excluded.custom_note,
      updated_at = excluded.updated_at
  """,
        (key, name, note),
    )
    return {"success": True}


@router.delete("/{key}")
async def delete_label(key: str):
    execute("DELETE FROM rule_labels WHERE rule_key = ?", (key,))
    return {"success": True}


@router.delete("")
async def delete_all_labels():
    execute("DELETE FROM rule_labels")
    return {"success": True}

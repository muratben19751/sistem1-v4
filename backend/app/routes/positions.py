import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_all

router = APIRouter()

_DIGITS_RE = re.compile(r"^\d+$")


def _parse_account_id(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not _DIGITS_RE.match(text):
        return None
    value = int(text)
    return value if value > 0 else None


@router.get("")
async def get_positions(request: Request):
    raw_account_id = request.query_params.get("accountId")
    account_id = _parse_account_id(raw_account_id)
    if raw_account_id is not None and account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    if account_id is not None:
        rows = query_all(
            "SELECT * FROM open_positions WHERE account_id = ? ORDER BY opened_at DESC",
            (account_id,),
        )
    else:
        rows = query_all("SELECT * FROM open_positions ORDER BY opened_at DESC")
    return [dict(r) for r in rows]

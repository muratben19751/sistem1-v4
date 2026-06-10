from fastapi import APIRouter, Request

from ..agents.replica_compare import build_comparison, start_replica_compare, stop_replica_compare

router = APIRouter()


@router.get("")
async def compare(request: Request):
    try:
        minutes = int(request.query_params.get("minutes") or "")
    except (TypeError, ValueError):
        minutes = 0
    return await build_comparison(minutes if minutes > 0 else 30)


@router.post("/start")
async def start():
    start_replica_compare()
    return {"success": True}


@router.post("/stop")
async def stop():
    stop_replica_compare()
    return {"success": True}

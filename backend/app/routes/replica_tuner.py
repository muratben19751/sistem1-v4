from fastapi import APIRouter

from ..agents.replica_tuner import (
    start_replica_tuner,
    stop_replica_tuner,
    tuner_state,
    run_tuner_cycle,
)
from ..agents.replica_compare import start_replica_compare
from ..agents import replica_params as rp

router = APIRouter()


@router.get("")
async def state():
    return tuner_state()


@router.post("/start")
async def start():
    start_replica_compare()
    start_replica_tuner()
    return {"success": True, "running": True}


@router.post("/stop")
async def stop():
    stop_replica_tuner()
    return {"success": True, "running": False}


@router.post("/run-once")
async def run_once():
    """Tek bir kalibrasyon dongusunu hemen calistirir (manuel tetik)."""
    return await run_tuner_cycle()


@router.post("/reset")
async def reset():
    """Tum replica parametrelerini env/varsayilan degerlere dondurur."""
    rp.reset()
    return {"success": True, "params": rp.snapshot()}

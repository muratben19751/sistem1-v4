import asyncio

from .core.logger import create_logger
from .db.database import get_db
from .db.migrations import run_migrations
from .agents.backtest_optimizer import run_optimizer_standalone

log = create_logger("optimizer-main")


async def _wait_for_schema(max_tries: int = 60) -> bool:
    for _ in range(max_tries):
        try:
            get_db().execute("SELECT 1 FROM optimizer_results LIMIT 1").fetchone()
            get_db().execute("SELECT 1 FROM app_config LIMIT 1").fetchone()
            return True
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2)
    return False


async def main() -> None:
    log.info("Optimizer process baslatiliyor, sema bekleniyor...")
    run_migrations()
    ok = await _wait_for_schema()
    if not ok:
        log.error("Gerekli tablolar bulunamadi (ana server migrate etmemis olabilir), cikiliyor.")
        return
    await run_optimizer_standalone()


if __name__ == "__main__":
    asyncio.run(main())

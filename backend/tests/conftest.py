"""Pytest oturum kurulumu — GERCEK DB/AG'a dokunmadan tam izole calisir.

Onemli: app.core.config ve app.db.database env'i *import aninda* okur. Bu yuzden
TUM env ayarlari, herhangi bir `app.*` importundan ONCE, bu modulun en ustunde
yapilmalidir.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

# ----- 1) Izole gecici DB + guvenli env (app importundan ONCE) -----
_TMP_DB = Path(tempfile.gettempdir()) / f"sistem1_v4_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_PATH"] = str(_TMP_DB)
# KRITIK: kimlik-anahtari dosyasini da izole et. Aksi halde ensure_credential_encryption()
# calistiran herhangi bir test GERCEK backend/data/.credential-key'i ezer ve canli
# kimlik bilgilerini cozulemez yapar (force-set: disaridan gelen gercek yolu da gecersiz kilar).
_TMP_CRED_KEY = Path(tempfile.gettempdir()) / f"sistem1_v4_test_credkey_{uuid.uuid4().hex}"
os.environ["CREDENTIAL_KEY_FILE"] = str(_TMP_CRED_KEY)
os.environ.setdefault("AUTH_TOKEN", "test-token-0123456789-abcdefgh")  # >=24 char
os.environ.setdefault("AUTH_TOKEN_MIN_LENGTH", "24")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "test-key-with-enough-entropy-xx")
os.environ.setdefault("APP_ENV", "test")
# Arka plan dongulerini kapat (route testleri lifespan calistirmaz ama yine de net olsun)
os.environ.setdefault("ENABLE_PRICE_UPDATER", "false")
os.environ.setdefault("OPTIMIZER_IN_SERVER", "false")
os.environ.setdefault("AUTO_START_BOTS", "false")
os.environ.setdefault("AUTO_START_OPTIMIZER", "false")

# backend/ kokunu import yoluna ekle (tests/ alt klasorunden calisinca da bulsun)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pytest  # noqa: E402

from app.db.database import DB_PATH, close_db  # noqa: E402
from app.db.migrations import run_migrations  # noqa: E402
from app.db.seed import seed_accounts  # noqa: E402

# Test DB'sinin gercekten izole gecici dosya oldugunu dogrula (canli DB'yi koru)
assert str(DB_PATH) == str(_TMP_DB.resolve()), f"Test DB izole degil: {DB_PATH}"
AUTH_TOKEN = os.environ["AUTH_TOKEN"]


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """Oturum basinda gecici DB'ye migration + seed uygula, sonunda temizle."""
    run_migrations()
    seed_accounts()
    yield
    try:
        close_db()
    finally:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(_TMP_DB) + suffix)
            try:
                p.unlink()
            except OSError:
                pass
        try:
            _TMP_CRED_KEY.unlink()
        except OSError:
            pass


@pytest.fixture()
def db():
    """Canli DB baglantisi (migration + seed uygulanmis gecici dosya)."""
    from app.db.database import get_db
    return get_db()


@pytest.fixture()
def seeded_account(db):
    """Seed edilmis ilk paper hesabin id'si + cuzdani."""
    row = db.execute("SELECT id FROM accounts WHERE type = 'paper' ORDER BY id LIMIT 1").fetchone()
    assert row is not None, "Seed paper hesabi bulunamadi"
    return row["id"]


@pytest.fixture()
async def client():
    """Auth'lu httpx ASGI istemcisi (lifespan CALISMAZ -> arka plan gorevi yok)."""
    import httpx
    from app.main import app as fastapi_app

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    ) as ac:
        yield ac


@pytest.fixture()
async def anon_client():
    """Auth basligi OLMAYAN istemci (401 testleri icin)."""
    import httpx
    from app.main import app as fastapi_app

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

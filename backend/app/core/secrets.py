import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .logger import create_logger

log = create_logger("secrets")

PREFIX = "enc:v1:"
_DEV_FALLBACK = "dev-token"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KEY_FILE = _BACKEND_ROOT / "data" / ".credential-key"
_invalid_credential_account_ids: set[int] = set()
_warned_dev_fallback = False


def _resolve_material() -> str:
    global _warned_dev_fallback
    material = (
        os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
        or _read_key_file()
        or os.environ.get("AUTH_TOKEN")
        or _DEV_FALLBACK
    )
    if material == _DEV_FALLBACK and not _warned_dev_fallback:
        _warned_dev_fallback = True
        log.error(
            "API kimlik bilgileri herkesce bilinen sabit 'dev-token' ile sifreleniyor "
            "(anahtar dosyasi yazilamadi ve AUTH_TOKEN yok) -> GERCEK GIZLILIK YOK. "
            "CREDENTIAL_ENCRYPTION_KEY ayarlayin veya data/ yazilabilir olsun."
        )
    return material


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def _key_file() -> Path:
    raw = os.environ.get("CREDENTIAL_KEY_FILE")
    if not raw:
        return _DEFAULT_KEY_FILE
    path = Path(raw)
    return path if path.is_absolute() else (_BACKEND_ROOT / path).resolve()


def _read_key_file() -> str | None:
    path = _key_file()
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except FileNotFoundError:
        return None


def _key_from_material(material: str) -> bytes:
    return hashlib.sha256(material.encode("utf-8")).digest()


def _encrypt_with_material(value: str, material: str) -> str:
    iv = os.urandom(12)
    encrypted_with_tag = AESGCM(_key_from_material(material)).encrypt(iv, value.encode("utf-8"), None)
    ciphertext = encrypted_with_tag[:-16]
    tag = encrypted_with_tag[-16:]
    return f"{PREFIX}{_b64url_encode(iv)}:{_b64url_encode(tag)}:{_b64url_encode(ciphertext)}"


def _decrypt_with_material(value: str, material: str) -> str:
    parts = value[len(PREFIX):].split(":")
    if len(parts) != 3:
        raise ValueError("Encrypted secret has invalid format")
    iv_raw, tag_raw, encrypted_raw = parts
    encrypted_with_tag = _b64url_decode(encrypted_raw) + _b64url_decode(tag_raw)
    return AESGCM(_key_from_material(material)).decrypt(
        _b64url_decode(iv_raw), encrypted_with_tag, None
    ).decode("utf-8")


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(PREFIX):
        return value
    material = _resolve_material()
    # Fail-secure: herkesce bilinen 'dev-token' ile YENI sifreleme yapilmaz (eski
    # kayitlarin cozulmesi ensure_credential_encryption fallback'inde korunur).
    if material == _DEV_FALLBACK:
        raise RuntimeError(
            "Kimlik bilgisi sifrelenemiyor: kalici anahtar yok (data/.credential-key "
            "yazilamadi ve CREDENTIAL_ENCRYPTION_KEY/AUTH_TOKEN ayarli degil)."
        )
    return _encrypt_with_material(value, material)


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    return _decrypt_with_material(value, _resolve_material())


def get_invalid_credential_account_ids() -> tuple[int, ...]:
    return tuple(sorted(_invalid_credential_account_ids))


def mark_credentials_valid(account_id: int) -> None:
    _invalid_credential_account_ids.discard(account_id)


def ensure_credential_encryption() -> int:
    """Create a dedicated key and migrate credentials encrypted with an older key."""
    from ..db.database import query_all, transaction
    global _invalid_credential_account_ids

    explicit = (os.environ.get("CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    file_material = _read_key_file()
    target = explicit or file_material
    if not target:
        target = _b64url_encode(os.urandom(48))

    fallback_materials = []
    for candidate in (file_material, os.environ.get("AUTH_TOKEN"), "dev-token"):
        if candidate and candidate != target and candidate not in fallback_materials:
            fallback_materials.append(candidate)

    rows = query_all(
        """
        SELECT id, api_key, api_secret FROM accounts
        WHERE api_key IS NOT NULL OR api_secret IS NOT NULL
        """
    )
    migrated: list[tuple[str | None, str | None, int]] = []
    invalid_account_ids: list[int] = []
    for row in rows:
        values: list[str | None] = []
        changed = False
        invalid = False
        for encrypted in (row["api_key"], row["api_secret"]):
            if not encrypted:
                values.append(encrypted)
                continue
            if not encrypted.startswith(PREFIX):
                values.append(_encrypt_with_material(encrypted, target))
                changed = True
                continue
            try:
                _decrypt_with_material(encrypted, target)
                values.append(encrypted)
                continue
            except Exception:  # noqa: BLE001
                plaintext = None
                for fallback in fallback_materials:
                    try:
                        plaintext = _decrypt_with_material(encrypted, fallback)
                        break
                    except Exception:  # noqa: BLE001
                        continue
                if plaintext is None:
                    invalid = True
                    break
                values.append(_encrypt_with_material(plaintext, target))
                changed = True
        if invalid:
            invalid_account_ids.append(int(row["id"]))
            continue
        if changed:
            migrated.append((values[0], values[1], row["id"]))

    key_path = _key_file()
    rotating_existing_file = bool(explicit and file_material and explicit != file_material)

    def write_key_file() -> None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = key_path.with_suffix(".tmp")
        temp_path.write_text(target + "\n", encoding="utf-8")
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, key_path)

    # A newly generated key must be durable before credentials are migrated.
    # During explicit rotation, keep the old file intact until the DB commit succeeds.
    if not rotating_existing_file:
        write_key_file()

    if migrated or invalid_account_ids:
        with transaction() as conn:
            if migrated:
                conn.executemany(
                    "UPDATE accounts SET api_key = ?, api_secret = ?, updated_at = datetime('now') WHERE id = ?",
                    migrated,
                )
            if invalid_account_ids:
                placeholders = ",".join("?" for _ in invalid_account_ids)
                conn.execute(
                    f"UPDATE bot_configs SET bot_enabled = 0 WHERE account_id IN ({placeholders})",
                    invalid_account_ids,
                )
    if rotating_existing_file:
        write_key_file()
    _invalid_credential_account_ids = set(invalid_account_ids)
    return len(migrated)

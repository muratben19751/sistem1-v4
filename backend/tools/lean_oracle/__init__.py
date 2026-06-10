import sys
from pathlib import Path

# backend kokunu import yoluna ekle ki `import app...` calissin (cwd'den bagimsiz).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

BACKEND_ROOT = _BACKEND_ROOT

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_APP_PATH = ROOT_DIR / 'boot-repair-app_0.0.3'
if str(CORE_APP_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_APP_PATH))

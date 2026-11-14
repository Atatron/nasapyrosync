"""Runtime configuration for PyroSync.

All settings come from environment variables (optionally loaded from a `.env`
file at the project root). Nothing secret is ever written to logs or responses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROCESSING_VERSION = "pyrosync-proc-1.0.0"
APP_VERSION = "1.2.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:  # empty values mean "use the default"
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: (PROJECT_ROOT / (os.environ.get("PYROSYNC_DATA_DIR") or "data")).resolve())
    host: str = field(default_factory=lambda: os.environ.get("PYROSYNC_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("PYROSYNC_PORT", "8000")))
    # Upload / ZIP safety limits
    max_upload_bytes: int = field(default_factory=lambda: int(os.environ.get("PYROSYNC_MAX_UPLOAD_MB", "2048")) * 1024 * 1024)
    max_zip_expanded_bytes: int = field(default_factory=lambda: int(os.environ.get("PYROSYNC_MAX_ZIP_EXPANDED_MB", "8192")) * 1024 * 1024)
    max_zip_entries: int = field(default_factory=lambda: int(os.environ.get("PYROSYNC_MAX_ZIP_ENTRIES", "50000")))
    max_zip_ratio: float = field(default_factory=lambda: float(os.environ.get("PYROSYNC_MAX_ZIP_RATIO", "200")))
    keep_raw_uploads: bool = field(default_factory=lambda: os.environ.get("PYROSYNC_KEEP_RAW_UPLOADS", "1") != "0")
    # Optional NASA FIRMS key: server-side only, never sent to the browser.
    firms_map_key: str = field(default_factory=lambda: os.environ.get("FIRMS_MAP_KEY", "").strip())
    firms_base_url: str = field(default_factory=lambda: os.environ.get("FIRMS_BASE_URL", "https://firms.modaps.eosdis.nasa.gov"))
    gibs_base_url: str = field(default_factory=lambda: os.environ.get("GIBS_BASE_URL", "https://gibs.earthdata.nasa.gov"))
    offline: bool = field(default_factory=lambda: os.environ.get("PYROSYNC_OFFLINE", "0") == "1")
    # Read-only public demo (e.g. Vercel): imports and FIRMS refresh are disabled; the database is
    # copied from a bundled seed file (PYROSYNC_SEED_DB) into the writable data dir on first use.
    readonly: bool = field(default_factory=lambda: os.environ.get("PYROSYNC_READONLY", "0") == "1")
    seed_db: str = field(default_factory=lambda: os.environ.get("PYROSYNC_SEED_DB", ""))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pyrosync.duckdb"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def aoi_dir(self) -> Path:
        return self.data_dir / "aois"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.raw_dir, self.cache_dir, self.reports_dir, self.aoi_dir, self.cache_dir / "firms"):
            p.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def set_settings(s: Settings) -> None:
    """Used by tests to point PyroSync at an isolated data directory."""
    global _settings
    s.ensure_dirs()
    _settings = s

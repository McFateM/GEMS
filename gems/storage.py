from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

MARKER = ".gems-storage"
MARKER_CONTENT = "GEMS storage v1\n"


def load_environment(env_file: str | None = None) -> None:
    selected = env_file or os.getenv("GEMS_ENV_FILE")
    if selected:
        path = Path(selected).expanduser()
        if not path.is_file():
            raise ValueError(f"Environment file does not exist: {path}")
        load_dotenv(path, override=False)
    else:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def atomic_json(path: Path, value: Any) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Storage:
    config: Path
    data: Path

    @classmethod
    def from_environment(cls) -> Storage:
        roots = []
        for name in ("GEMS_CONFIG_DIR", "GEMS_DATA_DIR"):
            raw = os.getenv(name, "")
            if not raw or not Path(raw).expanduser().is_absolute():
                raise ValueError(f"{name} must be an explicit absolute mounted directory in web mode.")
            path = Path(raw).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError(f"{name} is not a directory: {path}")
            roots.append(path)
        return cls(*roots)

    def initialize(self) -> None:
        for root in {self.config, self.data}:
            marker = root / MARKER
            if not marker.exists():
                with marker.open("x", encoding="utf-8") as handle:
                    handle.write(MARKER_CONTENT)
        self.check()

    def check(self) -> None:
        for root in {self.config, self.data}:
            if (root / MARKER).read_text(encoding="utf-8") != MARKER_CONTENT:
                raise ValueError(f"Invalid GEMS storage marker in {root}")
            with tempfile.TemporaryFile(dir=root) as handle:
                handle.write(b"GEMS storage check\n")
                handle.flush()
                os.fsync(handle.fileno())

    def data_path(self, raw: str, *, directory: bool = False) -> Path:
        if not raw.strip():
            raise ValueError("Enter a server path inside GEMS_DATA_DIR.")
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_relative_to(self.data):
            raise ValueError(f"Path must be inside GEMS_DATA_DIR: {path}")
        if directory and not path.is_dir():
            raise ValueError(f"Not a directory: {path}")
        if not directory and not path.is_file():
            raise ValueError(f"Not a file: {path}")
        return path

    def map_path(self, raw: str) -> Path:
        path = Path(raw).expanduser().resolve(strict=True)
        if not any(path.is_relative_to(root) for root in (self.config, self.data)):
            raise ValueError("Field maps must be inside GEMS_CONFIG_DIR or GEMS_DATA_DIR.")
        if not path.is_file():
            raise ValueError(f"Not a field map file: {path}")
        return path

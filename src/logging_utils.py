# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""
Utilities to configure and retrieve simulation loggers.

Logging is active when a 'logging' section is present in the JSON config;
omit the section to disable file/console output. This allows the user to
persist detailed traces of the simulation (agents, objects, collisions,
reasoning steps, ...).
"""
from __future__ import annotations

import csv
import hashlib
import logging
import shutil
import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_NAMESPACE = "sim"
HASH_LENGTH = 12
LOG_DIRNAME = "logs"
CONFIGS_SUBDIR = "configs"
HASH_MAP_FILENAME = "logs_configs_mapping.csv"

def _coerce_level(value: Any, default: int, key: str, warnings: list[str]) -> int:
    """
    Return a valid logging level from either a string or an integer.
    Append a warning message when a default is applied.
    """
    if value is None:
        warnings.append(f"Logging '{key}' not set; defaulting to {logging.getLevelName(default)}.")
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        candidate = getattr(logging, value.upper(), None)
        if isinstance(candidate, int):
            return candidate
    warnings.append(f"Logging '{key}' value {value!r} is invalid; defaulting to {logging.getLevelName(default)}.")
    return default

def configure_logging(
    settings: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
    project_root: Optional[str | Path] = None,
) -> None:
    """
    Configure Python logging based on the configuration dictionary.

    Parameters
    ----------
    settings:
        Dictionary coming from the config file. Supported keys:
        - file_level (str|int): logging level for persisted log (default: WARNING)
        - console_level (str|int): logging level for console (default: WARNING)
    config_path:
        Path to the configuration file being used for the simulation.
    project_root:
        Path to the repository root, used to derive the logs directory.
    """
    if settings is None:
        # Logging section missing -> disable logging.
        logging.basicConfig(level=logging.WARNING, handlers=[logging.NullHandler()], force=True)
        logging.getLogger(LOG_NAMESPACE).setLevel(logging.WARNING)
        return

    if not isinstance(settings, dict):
        settings = {}

    default_warnings: list[str] = []

    if "enabled" in settings:
        default_warnings.append("Logging 'enabled' is deprecated and ignored; logging is enabled when the 'logging' section is present.")

    # Console logging (only if explicitly enabled via 'console': true).
    console_enabled = bool(settings.get("console", False))
    console_level_value = settings.get("console_level")
    if console_level_value is None and "level" in settings:
        console_level_value = settings.get("level")
        default_warnings.append("Logging 'level' is deprecated; use 'console_level'.")
    console_level = _coerce_level(console_level_value, logging.WARNING, "console_level", default_warnings)

    # File logging
    file_level = _coerce_level(settings.get("file_level"), logging.WARNING, "file_level", default_warnings)

    handlers: list[logging.Handler] = []
    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        handlers.append(console_handler)

    log_context = _prepare_log_artifacts(config_path, project_root)
    log_path = log_context.get("log_path")
    if log_path:
        file_handler = _CompressedLogHandler(log_context, level=file_level)
        handlers.append(file_handler)

    if not handlers:
        null_handler = logging.NullHandler()
        null_handler.setLevel(logging.WARNING)
        handlers.append(null_handler)

    effective_level = min(handler.level for handler in handlers)

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=effective_level, handlers=handlers or None, force=True)
    logging.getLogger(LOG_NAMESPACE).setLevel(effective_level)
    # Silence noisy third-party debug (e.g., matplotlib font scanning) unless explicitly enabled elsewhere.
    logging.getLogger("matplotlib").setLevel(max(logging.WARNING, effective_level))

    logger = logging.getLogger(LOG_NAMESPACE)
    for msg in default_warnings:
        if handlers:
            logger.warning(msg)

def _prepare_log_artifacts(
    config_path: Optional[str | Path],
    project_root: Optional[str | Path],
) -> Dict[str, Optional[Path]]:
    """
    Compute log paths and metadata without touching the filesystem with files.
    Actual copying/writing is deferred until the first log entry is emitted.
    """
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]
    log_dir = root / LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cfg_path_obj = None
    cfg_hash = None
    if config_path:
        try:
            cfg_path_obj = Path(config_path).expanduser().resolve(strict=True)
            cfg_hash = hashlib.sha256(cfg_path_obj.read_bytes()).hexdigest()[:HASH_LENGTH]
        except FileNotFoundError:
            cfg_path_obj = None
            cfg_hash = None

    filename_parts = [timestamp]
    if cfg_hash:
        filename_parts.append(cfg_hash)
    log_stem = "_".join(filename_parts)
    inner_log_name = f"{log_stem}.log"
    archive_filename = f"{inner_log_name}.zip"
    log_path = log_dir / archive_filename

    return {
        "log_path": log_path,
        "inner_log_name": inner_log_name,
        "timestamp": timestamp,
        "config_path": cfg_path_obj,
        "config_hash": cfg_hash,
        "log_dir": log_dir,
        "project_root": root,
        "finalized": False,
    }

def _finalize_log_artifacts(context: Dict[str, Optional[Path]]) -> None:
    """
    Copy the config file (if any) and update the hash mapping.
    """
    if context.get("finalized"):
        return
    context["finalized"] = True
    cfg_path_obj: Optional[Path] = context.get("config_path")  # type: ignore[assignment]
    cfg_hash = context.get("config_hash")
    log_dir: Path = context["log_dir"]  # type: ignore[assignment]
    log_path: Path = context["log_path"]  # type: ignore[assignment]
    timestamp = context.get("timestamp")
    project_root: Path = context["project_root"]  # type: ignore[assignment]

    if cfg_path_obj and cfg_hash:
        configs_dir = log_dir / CONFIGS_SUBDIR
        configs_dir.mkdir(parents=True, exist_ok=True)
        cfg_copy_name = f"{timestamp}_{cfg_hash}_{cfg_path_obj.name}"
        shutil.copy2(cfg_path_obj, configs_dir / cfg_copy_name)
        _update_hash_mapping(log_dir / HASH_MAP_FILENAME, cfg_hash, log_path, project_root)

def _update_hash_mapping(mapping_file: Path, cfg_hash: str, log_path: Path, project_root: Path) -> None:
    """
    Append/update the CSV file that maps config hashes to log files.
    """
    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    need_header = not mapping_file.exists()
    rel_path: str
    try:
        rel_path = log_path.relative_to(project_root).as_posix()
    except ValueError:
        rel_path = str(log_path.resolve())
    else:
        rel_path = f"{project_root.name}/{rel_path}"
    with mapping_file.open("a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if need_header:
            writer.writerow(["hash", "log_path"])
        writer.writerow([cfg_hash, rel_path])

def get_logger(component: str) -> logging.Logger:
    """
    Return a namespaced logger for the given component.
    """
    component = component.strip(".")
    name = f"{LOG_NAMESPACE}.{component}" if component else LOG_NAMESPACE
    return logging.getLogger(name)

class _CompressedLogHandler(logging.Handler):
    """
    Deferred handler that writes logs inside a ZIP archive with maximum compression.
    The archive and config artifacts are created only when the first record arrives.
    """

    terminator = "\n"

    def __init__(self, context: Dict[str, Optional[Path]], level: int) -> None:
        super().__init__(level)
        self._context = context
        self._zip: Optional[zipfile.ZipFile] = None
        self._stream: Optional[io.TextIOWrapper] = None
        self._inner_stream: Optional[zipfile.ZipExtFile] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = self._ensure_stream()
            msg = self.format(record)
            stream.write(msg + self.terminator)
            stream.flush()
        except Exception:
            self.handleError(record)

    def _ensure_stream(self) -> io.TextIOWrapper:
        if self._stream is None:
            self._activate()
        assert self._stream is not None
        return self._stream

    def _activate(self) -> None:
        archive_path: Path = self._context["log_path"]  # type: ignore[assignment]
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        self._zip = zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        )
        inner_name = self._context.get("inner_log_name") or archive_path.stem + ".log"
        self._inner_stream = self._zip.open(inner_name, mode="w")
        self._stream = io.TextIOWrapper(self._inner_stream, encoding="utf-8")
        _finalize_log_artifacts(self._context)

    def flush(self) -> None:
        if self._stream:
            self._stream.flush()

    def close(self) -> None:
        try:
            if self._stream:
                self._stream.close()
            if self._zip:
                self._zip.close()
        finally:
            self._stream = None
            self._inner_stream = None
            self._zip = None
        super().close()

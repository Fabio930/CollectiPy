# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
# ------------------------------------------------------------------------------

"""
Utilities to configure and retrieve simulation loggers.

This version implements **per-process logging**:
each process writes its own compressed ZIP log safely.

Directory layout:
    logs/MainProcess/<timestamp>.log.zip
    logs/Process-1/<timestamp>.log.zip
    logs/message_server/<timestamp>.log.zip
    ...
"""

from __future__ import annotations

import csv
import hashlib
import logging
import shutil
import io
import zipfile
import os
import multiprocessing as mp
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_NAMESPACE = "sim"
HASH_LENGTH = 12
LOG_DIRNAME = "logs"
CONFIGS_SUBDIR = "configs"
HASH_MAP_FILENAME = "logs_configs_mapping.csv"


# ------------------------------------------------------------------------------
#  MAIN ENTRY POINT
# ------------------------------------------------------------------------------

def configure_logging(
    settings: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
    project_root: Optional[str | Path] = None,
    base_path: Optional[str | Path] = None,
) -> None:
    """
    Configure logging for this process.
    Each process writes its own compressed ZIP to logs/<process-name>/.

    settings keys:
        - level: global log level
        - to_file: enable ZIP logging
    """

    # Default: disable logging
    if settings is None:
        logging.basicConfig(
            level=logging.WARNING,
            handlers=[logging.NullHandler()],
            force=True,
        )
        return

    if not isinstance(settings, dict):
        settings = {}

    # Interpret level
    level_raw = settings.get("level", "WARNING")
    level = getattr(logging, str(level_raw).upper(), logging.WARNING)
    to_file = bool(settings.get("to_file", False))

    # Build handlers
    handlers: list[logging.Handler] = []

    # Console handler (all processes)
    console = logging.StreamHandler()
    console.setLevel(level)
    handlers.append(console)

    # Determine root path
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]

    # Build log directory base for this process
    proc_name = mp.current_process().name

    # If no custom path → logs/<process-name>/
    if to_file:
        if base_path is None:
            base_path = Path(root) / LOG_DIRNAME / proc_name

        log_context = _prepare_log_artifacts(config_path, root, base_path)
        file_handler = _CompressedLogHandler(log_context)

        # File handler accepts ALL levels (root decides)
        file_handler.setLevel(logging.NOTSET)
        handlers.append(file_handler)

    # Apply configuration
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,
    )

    # Namespace logger
    sim_logger = logging.getLogger(LOG_NAMESPACE)
    sim_logger.setLevel(level)
    sim_logger.propagate = True

    # Set formatter
    formatter = logging.Formatter(LOG_FORMAT)
    for h in handlers:
        h.setFormatter(formatter)

    # Silence very noisy modules
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


# ------------------------------------------------------------------------------
#  PATH PREPARATION
# ------------------------------------------------------------------------------

def _prepare_log_artifacts(
    config_path: Optional[str | Path],
    project_root: Path,
    base_path: Optional[str | Path]
) -> Dict[str, Path | str | bool | None]:

    log_dir = Path(base_path).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    cfg_path_obj = None
    cfg_hash = None
    if config_path:
        try:
            cfg_path_obj = Path(config_path).expanduser().resolve(strict=True)
            cfg_hash = hashlib.sha256(cfg_path_obj.read_bytes()).hexdigest()[:HASH_LENGTH]
        except FileNotFoundError:
            pass

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
        "project_root": project_root,
        "finalized": False,
    }


# ------------------------------------------------------------------------------
#  FINALIZATION (copy config + map)
# ------------------------------------------------------------------------------

def _finalize_log_artifacts(context: Dict[str, Path | str | bool | None]) -> None:
    if context.get("finalized"):
        return
    context["finalized"] = True

    cfg_path_obj = context.get("config_path")
    cfg_hash = context.get("config_hash")
    log_dir = context["log_dir"]
    log_path = context["log_path"]
    timestamp = context["timestamp"]
    project_root = context["project_root"]

    if cfg_path_obj and cfg_hash:
        configs_dir = log_dir / CONFIGS_SUBDIR
        configs_dir.mkdir(parents=True, exist_ok=True)
        cfg_copy_name = f"{timestamp}_{cfg_hash}_{cfg_path_obj.name}"
        shutil.copy2(cfg_path_obj, configs_dir / cfg_copy_name)

        _update_hash_mapping(log_dir / HASH_MAP_FILENAME, cfg_hash, log_path, project_root)


def _update_hash_mapping(mapping_file: Path, cfg_hash: str, log_path: Path, project_root: Path) -> None:
    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    need_header = not mapping_file.exists()

    try:
        rel_path = log_path.relative_to(project_root).as_posix()
        rel_path = f"{project_root.name}/{rel_path}"
    except Exception:
        rel_path = str(log_path.resolve())

    with mapping_file.open("a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if need_header:
            writer.writerow(["hash", "log_path"])
        writer.writerow([cfg_hash, rel_path])


# ------------------------------------------------------------------------------
#  LOGGER ACCESS
# ------------------------------------------------------------------------------

def get_logger(component: str) -> logging.Logger:
    """Return logger sim.<component>."""
    component = component.strip(".")
    name = f"{LOG_NAMESPACE}.{component}" if component else LOG_NAMESPACE
    return logging.getLogger(name)


# ------------------------------------------------------------------------------
#  COMPRESSED ZIP HANDLER (per process)
# ------------------------------------------------------------------------------
class _CompressedLogHandler(logging.Handler):
    """
    Creates a ZIP archive for this process and writes logs inside it.
    """

    terminator = b"\n"   # in binario

    def __init__(self, context):
        super().__init__()
        self._context = context
        self._zip = None
        self._inner_stream = None
        self._activate()

    def _activate(self):
        archive_path: Path = self._context["log_path"]
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        self._zip = zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        )

        inner_name = self._context["inner_log_name"]

        # IMPORTANT: write in binary mode only
        self._inner_stream = self._zip.open(inner_name, mode="w")

        _finalize_log_artifacts(self._context)

    def emit(self, record):
        try:
            msg = self.format(record).encode("utf-8") + self.terminator
            self._inner_stream.write(msg)
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            if self._inner_stream:
                self._inner_stream.close()
        except:
            pass

        try:
            if self._zip:
                self._zip.close()
        except:
            pass

        self._inner_stream = None
        self._zip = None

        super().close()

# ------------------------------------------------------------------------------
#  CLEAN SHUTDOWN
# ------------------------------------------------------------------------------

def shutdown_logging():
    """Flush and close all logging handlers."""
    root = logging.getLogger()
    for h in root.handlers[:]:
        try: h.flush()
        except: pass
        try: h.close()
        except: pass
        root.removeHandler(h)
    logging.shutdown()

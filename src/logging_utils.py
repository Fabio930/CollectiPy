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

Default directory layout (base_path="data/logs"):
    data/logs/MainProcess/<timestamp>.log.zip
    data/logs/Process-1/<timestamp>.log.zip
    data/logs/message_server/<timestamp>.log.zip
    ...
"""

from __future__ import annotations

import logging
import zipfile
import multiprocessing as mp
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from utils.folder_utils import DEFAULT_RESULTS_BASE, LOG_DIRNAME as DEFAULT_LOG_DIRNAME


LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_NAMESPACE = "sim"
LOG_DIRNAME = DEFAULT_LOG_DIRNAME
DEFAULT_LOG_BASE = Path(DEFAULT_RESULTS_BASE) / LOG_DIRNAME


def is_logging_enabled(settings: Optional[Dict[str, Any]]) -> bool:
    """Return True when at least one logging handler should be active."""
    if not isinstance(settings, dict):
        return False
    to_file = settings.get("to_file")
    to_console = settings.get("to_console")
    if to_file is None and to_console is None:
        return True
    return bool(to_file) or bool(to_console)


def is_file_logging_enabled(settings: Optional[Dict[str, Any]]) -> bool:
    """Return True when file logging should run (defaults to True when enabled)."""
    if not isinstance(settings, dict):
        return False
    if "to_file" in settings:
        return bool(settings["to_file"])
    return True


# ------------------------------------------------------------------------------
#  MAIN ENTRY POINT
# ------------------------------------------------------------------------------

def configure_logging(
    settings: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
    project_root: Optional[str | Path] = None,
    base_path: Optional[str | Path] = None,
    log_filename_prefix: Optional[str] = None,
) -> None:
    """
    Configure logging for this process.
    Each process writes its own compressed ZIP to logs/<process-name>/.

    settings keys:
        - level: global log level (defaults to WARNING)
        - to_file: enable ZIP logging (defaults to True when a logging block is provided)
        - to_console: mirror logs to stdout/stderr (defaults to False)
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
    to_file = settings.get("to_file") if "to_file" in settings else True
    to_file = bool(to_file)

    # Build handlers
    handlers: list[logging.Handler] = []

    # Console handler (optional)
    to_console = bool(settings.get("to_console", False))
    if to_console:
        console = logging.StreamHandler()
        console.setLevel(level)
        handlers.append(console)

    # Determine root path
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]

    # Build log directory base for this process
    proc_name = mp.current_process().name

    # If no custom path → data/logs/<process-name>/ (default base)
    if to_file:
        if base_path is None:
            base_path = Path(root) / DEFAULT_LOG_BASE / proc_name

        log_context = _prepare_log_artifacts(
            config_path,
            root,
            base_path,
            filename_prefix=log_filename_prefix,
        )
        file_handler = _CompressedLogHandler(log_context)

        # File handler accepts ALL levels (root decides)
        file_handler.setLevel(logging.NOTSET)
        handlers.append(file_handler)

    if not handlers:
        handlers.append(logging.NullHandler())

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
    base_path: Optional[str | Path],
    filename_prefix: Optional[str] = None,
) -> Dict[str, Path | str | bool | None]:

    log_dir = Path(base_path).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    filename_parts = []
    if filename_prefix:
        filename_parts.append(filename_prefix)
    filename_parts.append(timestamp)

    log_stem = "_".join(filename_parts)
    inner_log_name = f"{log_stem}.log"
    archive_filename = f"{inner_log_name}.zip"
    log_path = log_dir / archive_filename

    return {
        "log_path": log_path,
        "inner_log_name": inner_log_name,
        "timestamp": timestamp,
        "log_dir": log_dir,
        "project_root": project_root,
    }


# ------------------------------------------------------------------------------
#  FINALIZATION (copy config + map)
# ------------------------------------------------------------------------------

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


    def emit(self, record):
        try:
            msg = self.format(record).encode("utf-8") + self.terminator
            self._inner_stream.write(msg)
            self._inner_stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            if self._inner_stream:
                self._inner_stream.flush()
                self._inner_stream.close()
        except:
            pass

        try:
            if self._zip:
                self._zip.fp.flush()
                self._zip.close()
        except:
            pass

        self._inner_stream = None
        self._zip = None

        super().close()

# ------------------------------------------------------------------------------
#  CLEAN SHUTDOWN
# ------------------------------------------------------------------------------


def _settings_without_file(settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of settings with file logging disabled."""
    if not isinstance(settings, dict):
        return None
    clone = dict(settings)
    clone["to_file"] = False
    return clone


def initialize_process_console_logging(
    settings: Optional[Dict[str, Any]],
    config_path: Optional[str | Path],
    project_root: Optional[str | Path],
) -> None:
    """Ensure the process has at least a console logger during startup."""
    configure_logging(
        _settings_without_file(settings),
        config_path,
        project_root,
        log_filename_prefix=None,
    )


def start_run_logging(
    log_specs: Optional[Dict[str, Any]],
    process_name: str,
    run_number: int,
) -> None:
    """Switch the logging handlers to a new ZIP file for the given run."""
    settings = log_specs.get("settings") if log_specs else None
    config_path = log_specs.get("config_path") if log_specs else None
    project_root = log_specs.get("project_root") if log_specs else None
    runs_root = log_specs.get("runs_root") if log_specs else None
    process_folder = log_specs.get("process_folder") if log_specs else None
    log_filename_prefix = log_specs.get("log_file_prefix") if log_specs else None
    if not log_filename_prefix:
        log_filename_prefix = process_name

    if process_folder is None:
        folder_name = process_name
    elif process_folder == "":
        folder_name = None
    else:
        folder_name = process_folder

    logging_enabled = is_logging_enabled(settings)
    file_logging_enabled = is_file_logging_enabled(settings) if logging_enabled else False

    if not logging_enabled:
        shutdown_logging()
        configure_logging(None, config_path, project_root)
        return

    base_path = None
    if file_logging_enabled:
        if runs_root:
            base_root = Path(runs_root) / f"run_{run_number}"
            if folder_name:
                base_path = base_root / folder_name
            else:
                base_path = base_root
        else:
            base_root = Path(project_root or Path.cwd()) / DEFAULT_LOG_BASE
            if folder_name:
                base_root = base_root / folder_name
            base_path = base_root / f"run_{run_number}"
    shutdown_logging()
    configure_logging(
        settings,
        config_path,
        project_root,
        base_path=base_path,
        log_filename_prefix=log_filename_prefix,
    )


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

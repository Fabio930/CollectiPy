# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Environment factory."""
from __future__ import annotations

from pathlib import Path

from core.configuration.config import Config
from core.main.environment.runtime import Environment


class EnvironmentFactory:
    """Environment factory."""

    @staticmethod
    def create_environment(config_elem: Config, config_path, log_root: Path | None = None):
        """Create environment."""
        if config_elem.environment:
            return Environment(config_elem, config_path, log_root=log_root)
        msg = (
            f"Invalid environment configuration: "
            f"{config_elem.environment['parallel_experiments']} "
            f"{config_elem.environment['render']}"
        )
        raise ValueError(msg)

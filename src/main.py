# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import sys, getopt, logging
from pathlib import Path
from config import Config
from environment import EnvironmentFactory
from plugin_registry import load_plugins_from_config
from logging_utils import configure_logging

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

def print_usage(errcode=None):
    """Print usage."""
    print("Usage: python main.py -c <config_file_path>")
    sys.exit(errcode)

def main(argv):
    """Parse arguments and start the simulator."""
    configfile = ""
    try:
        opts, args = getopt.getopt(argv, "hc:", ["config="])
    except getopt.GetoptError:
        logging.fatal("Error in parsing command line arguments")
        print_usage(1)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print_usage()
        elif opt in ("-c", "--config"):
            configfile = arg
    if not configfile:
        logging.fatal("No configuration file provided")
        print_usage(1)
    config_path_resolved = None
    if configfile:
        config_path_resolved = Path(configfile).expanduser().resolve()
    try:
        my_config = Config(config_path=configfile)
        configure_logging(
            my_config.environment.get("logging"),
            config_path=config_path_resolved,
            project_root=ROOT_DIR,
        )
        # Load any external plugins declared in the config (optional).
        load_plugins_from_config(my_config)
        my_env = EnvironmentFactory.create_environment(my_config)
        my_env.start()
    except Exception as e:
        logging.fatal(f"Failed to create environment: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])

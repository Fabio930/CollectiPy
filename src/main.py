import sys, getopt, logging, json
from pathlib import Path
from config import Config
from environment import EnvironmentFactory
from plugin_registry import load_plugins_from_config
from logging_utils import configure_logging, is_logging_enabled, shutdown_logging
from utils.folder_utils import (
    derive_experiment_folder_basename,
    generate_shared_unique_folder_name,
    resolve_base_dirs,
    resolve_result_specs,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

def print_usage(errcode=None):
    print("Usage: python main.py -c <config_file_path>")
    sys.exit(errcode)

def main(argv):
    configfile = ""
    try:
        opts, args = getopt.getopt(argv, "hc:", ["config="])
    except getopt.GetoptError:
        logging.fatal("Error in parsing argument list")
        print_usage(1)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print_usage()
        elif opt in ("-c", "--config"):
            configfile = arg

    if not configfile:
        logging.fatal("No configuration file provided")
        print_usage(1)

    config_path_resolved = Path(configfile).expanduser().resolve()

    exit_code = 0
    try:
        # IMPORTANT: use the resolved path
        my_config = Config(config_path=config_path_resolved)
        logging_cfg = my_config.environment.get("logging")
        results_cfg = my_config.environment.get("results", {}) or {}
        agent_specs, group_specs = resolve_result_specs(results_cfg)
        logging_enabled = is_logging_enabled(logging_cfg)
        results_enabled = bool(results_cfg)

        session_folder = None
        if logging_enabled:
            results_root, logs_root = resolve_base_dirs(logging_cfg, results_cfg)
            logs_root.mkdir(parents=True, exist_ok=True)
            if results_enabled:
                results_root.mkdir(parents=True, exist_ok=True)
            folder_base = derive_experiment_folder_basename(
                my_config, agent_specs=agent_specs, group_specs=group_specs
            )
            base_paths = tuple(p for p in (logs_root, results_root if results_enabled else None) if p)
            session_folder_name = generate_shared_unique_folder_name(base_paths, folder_base)
            session_folder = logs_root / session_folder_name
            session_folder.mkdir(parents=True, exist_ok=True)
            with open(session_folder / "config.json", "w", encoding="utf-8") as cfg_file:
                json.dump(my_config.data, cfg_file, indent=4, default=str)

        # Configure logging for MainProcess ONLY
        configure_logging(
            logging_cfg,
            config_path=config_path_resolved,
            project_root=ROOT_DIR,
            base_path=session_folder / "main" if session_folder else None,
            log_filename_prefix=None,
        )

        # Load optional plugins
        load_plugins_from_config(my_config)

        # Environment creation does NOT configure logging anymore
        my_env = EnvironmentFactory.create_environment(
            my_config,
            config_path_resolved,
            log_root=session_folder if logging_enabled else None,
        )

        my_env.start()

    except Exception as e:
        logging.fatal(f"Failed to create environment: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1

    finally:
        sys.exit(exit_code)

if __name__ == "__main__":
    main(sys.argv[1:])

# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Environment: process-level orchestration of the simulation."""
import logging, psutil, gc
import multiprocessing as mp
from config import Config
from entity import EntityFactory
from arena import ArenaFactory
from gui import GuiFactory
from entityManager import EntityManager
from collision_detector import CollisionDetector

class _PipeQueue:
    """Single-producer/single-consumer queue backed by Pipe with poll()."""
    def __init__(self, ctx: mp.context.BaseContext):
        self._recv, self._send = ctx.Pipe(duplex=False)

    def put(self, item):
        self._send.send(item)

    def get(self):
        return self._recv.recv()

    def poll(self, timeout: float = 0.0):
        return self._recv.poll(timeout)

    def qsize(self):
        return 1 if self._recv.poll(0) else 0

    def empty(self):
        return not self._recv.poll(0)

class EnvironmentFactory():
    """Environment factory."""
    @staticmethod
    def create_environment(config_elem:Config):
        """Create environment."""
        if not config_elem.environment.get("parallel_experiments",False) or config_elem.environment["render"]:
            return SingleProcessEnvironment(config_elem)
        elif config_elem.environment.get("parallel_experiments",False) and not config_elem.environment["render"]:
            return MultiProcessEnvironment(config_elem)
        else:
            raise ValueError(f"Invalid environment configuration: {config_elem.environment['parallel_experiments']} {config_elem.environment['render']}")

class Environment():
    """Environment."""
    def __init__(self,config_elem:Config):
        """Initialize the instance."""
        self.experiments = config_elem.parse_experiments()
        self.num_runs = int(config_elem.environment.get("num_runs",1))
        self.time_limit = int(config_elem.environment.get("time_limit",0))
        self.gui_id = config_elem.gui.get("_id","2D")
        self.render = [True,config_elem.gui] if len(config_elem.gui)>0 else [False,{}]
        self.collisions = config_elem.environment.get("collisions",False)
        if not self.render[0] and self.time_limit==0:
            raise Exception("Invalid configuration: infinite experiment with no GUI.")

    def start(self):
        """Start the process."""
        pass

class SingleProcessEnvironment(Environment):
    """Single process environment."""
    def __init__(self,config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        logging.info("Single process environment created successfully")

    def arena_init(self,exp:Config):
        """Arena init."""
        arena = ArenaFactory.create_arena(exp)
        if self.num_runs > 1 and arena.get_seed() < 0:
            arena.reset_seed()
        arena.initialize()
        return arena

    def agents_init(self,exp:Config):
        """Agents init."""
        agents = {agent_type: (exp.environment.get("agents").get(agent_type),[]) for agent_type in exp.environment.get("agents").keys()}
        for key,(config,entities) in agents.items():
            for n in range(config["number"]):
                entities.append(EntityFactory.create_entity(entity_type="agent_"+key,config_elem=config,_id=n))
        logging.info(f"Agents initialized: {list(agents.keys())}")
        return agents

    def run_gui(self, config:dict, arena_vertices:list, arena_color:str, gui_in_queue, gui_control_queue, wrap_config=None, hierarchy_overlay=None):
        """Run the gui."""
        app, gui = GuiFactory.create_gui(
            config,
            arena_vertices,
            arena_color,
            gui_in_queue,
            gui_control_queue,
            wrap_config=wrap_config,
            hierarchy_overlay=hierarchy_overlay
        )
        gui.show()
        app.exec()

    def start(self):
        """Start the process."""
        ctx = mp.get_context("fork")
        for exp in self.experiments:
            arena_queue = _PipeQueue(ctx)
            agents_queue = _PipeQueue(ctx)
            dec_arena_in = _PipeQueue(ctx)
            dec_agents_in = _PipeQueue(ctx)
            dec_agents_out = _PipeQueue(ctx)
            gui_in_queue = _PipeQueue(ctx)
            gui_control_queue = _PipeQueue(ctx)
            arena = self.arena_init(exp)
            agents = self.agents_init(exp)
            arena_shape = arena.get_shape()
            arena_id = arena.get_id()
            render_enabled = self.render[0]
            wrap_config = arena.get_wrap_config()
            arena_hierarchy = arena.get_hierarchy()
            collision_detector = CollisionDetector(arena_shape, self.collisions, wrap_config=wrap_config)
            entity_manager = EntityManager(agents, arena_shape, wrap_config=wrap_config, hierarchy=arena_hierarchy)
            arena_process = mp.Process(target=arena.run, args=(self.num_runs, self.time_limit, arena_queue, agents_queue, gui_in_queue, dec_arena_in, gui_control_queue, render_enabled))
            agents_process = mp.Process(target=entity_manager.run, args=(self.num_runs, self.time_limit, arena_queue, agents_queue, dec_agents_in, dec_agents_out))
            detector_process = mp.Process(target=collision_detector.run, args=(dec_agents_in, dec_agents_out, dec_arena_in))

            killed = 0
            if render_enabled:
                self.render[1]["_id"] = "abstract" if arena_id in (None, "none") else self.gui_id
                hierarchy_overlay = arena_hierarchy.to_rectangles() if arena_hierarchy else None
                gui_process = mp.Process(
                    target=self.run_gui,
                    args=(
                        self.render[1],
                        arena_shape.vertices(),
                        arena_shape.color(),
                        gui_in_queue,
                        gui_control_queue,
                        wrap_config,
                        hierarchy_overlay
                    )
                )
                gui_process.start()
                if arena_id not in ("abstract", "none", None):
                    detector_process.start()
                agents_process.start()
                arena_process.start()
                while True:
                    arena_alive = arena_process.is_alive()
                    agents_alive = agents_process.is_alive()
                    gui_alive = gui_process.is_alive()
                    detector_alive = detector_process.is_alive() if detector_process.pid is not None else False
                    arena_exit = arena_process.exitcode
                    agents_exit = agents_process.exitcode
                    gui_exit = gui_process.exitcode
                    # Check for process failures
                    if arena_exit not in (None, 0):
                        killed = 1
                        if agents_alive: agents_process.terminate()
                        if gui_alive: gui_process.terminate()
                        if detector_alive: detector_process.terminate()
                        if arena_process.pid is not None: arena_process.join()
                        if agents_process.pid is not None: agents_process.join()
                        if detector_process.pid is not None: detector_process.join()
                        if gui_process.pid is not None: gui_process.join()
                        arena.close()
                        entity_manager.close()
                        raise RuntimeError("A subprocess exited unexpectedly.")
                    elif agents_exit not in (None, 0):
                        killed = 1
                        if arena_alive: arena_process.terminate()
                        if gui_alive: gui_process.terminate()
                        if detector_alive: detector_process.terminate()
                        if arena_process.pid is not None: arena_process.join()
                        if agents_process.pid is not None: agents_process.join()
                        if detector_process.pid is not None: detector_process.join()
                        if gui_process.pid is not None: gui_process.join()
                        arena.close()
                        entity_manager.close()
                        raise RuntimeError("A subprocess exited unexpectedly.")
                    elif render_enabled and gui_exit not in (None, 0):
                        killed = 1
                        if arena_alive: arena_process.terminate()
                        if agents_alive: agents_process.terminate()
                        if detector_alive: detector_process.terminate()
                        if arena_process.pid is not None: arena_process.join()
                        if agents_process.pid is not None: agents_process.join()
                        if detector_process.pid is not None: detector_process.join()
                        if gui_process.pid is not None: gui_process.join()
                        arena.close()
                        entity_manager.close()
                        raise RuntimeError("A subprocess exited unexpectedly.")
                    # Zombie/Dead GUI process
                    if killed == 0 and gui_process.pid is not None:
                        try:
                            gui_status = psutil.Process(gui_process.pid).status()
                        except psutil.NoSuchProcess:
                            gui_status = psutil.STATUS_DEAD
                        if gui_status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                            killed = 1
                            if arena_alive: arena_process.terminate()
                            if agents_alive: agents_process.terminate()
                            if detector_alive: detector_process.terminate()
                            arena.close()
                            entity_manager.close()
                            break
                    if not arena_alive:
                        if agents_alive: agents_process.terminate()
                        if detector_alive: detector_process.terminate()
                        if gui_alive: gui_process.terminate()
                        arena.close()
                        entity_manager.close()
                        break
                # Join all processes
                if arena_process.pid is not None: arena_process.join()
                if agents_process.pid is not None: agents_process.join()
                if detector_process.pid is not None: detector_process.join()
                if gui_process.pid is not None: gui_process.join()
            else:
                if arena_id not in ("abstract", "none", None):
                    detector_process.start()
                agents_process.start()
                arena_process.start()
                while arena_process.is_alive() and agents_process.is_alive():
                    arena_process.join(timeout=0.1)
                    agents_process.join(timeout=0.1)
                killed = 0
                if arena_process.exitcode not in (None, 0):
                    killed = 1
                    if agents_process.is_alive(): agents_process.terminate()
                    if detector_process.is_alive(): detector_process.terminate()
                elif agents_process.exitcode not in (None, 0):
                    killed = 1
                    if arena_process.is_alive(): arena_process.terminate()
                    if detector_process.is_alive(): detector_process.terminate()
                # Join all processes
                if arena_process.pid is not None: arena_process.join()
                if agents_process.pid is not None: agents_process.join()
                if detector_process.pid is not None:
                    detector_process.terminate()
                    detector_process.join()
                arena.close()
                entity_manager.close()
                if killed == 1:
                    raise RuntimeError("A subprocess exited unexpectedly.")
            gc.collect()
        logging.info("All experiments completed successfully")

class MultiProcessEnvironment(Environment):
    """Multi process environment."""
    def __init__(self,config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        logging.info("Multi process environment created successfully")

    def start(self):
        """Start the process."""
        pass

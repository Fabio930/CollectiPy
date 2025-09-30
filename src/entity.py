import math, json, hashlib
import numpy as np
from random import Random
from geometry_utils.vector3D import Vector3D
from bodies.shapes3D import Shape3DFactory
from spinsystem import SpinSystem

_PI = math.pi
class EntityFactory:
    
    @staticmethod
    def create_entity(entity_type:str,config_elem: dict,_id:int=0):
        check_type = entity_type.split('_')[0]+'_'+entity_type.split('_')[1]
        if check_type == "agent_static":
            return StaticAgent(entity_type,config_elem,_id)
        elif check_type == "agent_movable":
            return MovableAgent(entity_type,config_elem,_id)
        elif check_type == "object_static":
            return StaticObject(entity_type,config_elem,_id)
        elif check_type == "object_movable":
            return MovableObject(entity_type,config_elem,_id)
        else:
            raise ValueError(f"Invalid agent type: {entity_type}")

class Entity:
    def __init__(self,entity_type:str, config_elem: dict,_id:int=0):
        self.entity_type = entity_type
        self._id = _id
        self.position_from_dict = False
        self.orientation_from_dict = False
        self.color = config_elem.get("color","black")
    
    def get_name(self):
        return self.entity_type+"_"+str(self._id)

    def get_position_from_dict(self):
        return self.position_from_dict
    
    def get_orientation_from_dict(self):
        return self.orientation_from_dict

    def reset(self):
        pass

    def entity(self) -> str:
        return self.entity_type
    
class Object(Entity):    
    def __init__(self,entity_type:str, config_elem: dict,_id:int=0):
        super().__init__(entity_type,config_elem,_id)
        if not config_elem.get("_id") in ("idle","interactive"):
            raise ValueError(f"Invalid object type: {self.entity_type}")

class Agent(Entity):
    def __init__(self, entity_type:str, config_elem:dict, _id:int=0):
        super().__init__(entity_type, config_elem, _id)
        self.random_generator = Random()
        self.ticks_per_second = config_elem.get("ticks_per_second", 31)
        self.color = config_elem.get("color", "blue")
        # --- messaging ---
        self.messages_config = config_elem.get("messages", {})
        self.msg_enable = True if len(self.messages_config) > 0 else False
        self.msg_comm_range = self.messages_config.get("comm_range", 0.1)
        self.msg_type = self.messages_config.get("type", "broadcast")
        self.msg_kind = self.messages_config.get("kind", "anonymous")
        self.msgs_per_sec = self.messages_config.get("messages_per_seconds", 1)
        self.msg_ticks_interval = max(1, int(self.ticks_per_second / self.msgs_per_sec))
        self.message_bus = None
        self.own_message = {}
        self.messages = []

    def set_message_bus(self, bus):
        self.message_bus = bus

    def should_send_message(self, tick):
        return self.msg_enable and ((tick - 1) % self.msg_ticks_interval == 0)

    def send_message(self,tick):
        if self.should_send_message(tick) and self.message_bus:
            self.own_message = {"tick":tick}
            self.message_bus.send_message(self, self.own_message)

    def receive_messages(self):
        if self.msg_enable and self.message_bus:
            messages = self.message_bus.receive_messages(self)
            if len(messages) > 0: self.messages.extend(messages)
            return messages
        return []
    
    def ticks(self): return self.ticks_per_second
    
    def set_random_generator(self,config,random_seed):
        config_str = json.dumps(config, sort_keys=True)
        config_seed = int(hashlib.sha256(config_str.encode()).hexdigest(), 16) % (2**32)
        seed = int(hashlib.sha256(f"{config_seed}_{random_seed}_{int(self.entity_type.split('_')[-1])}_{int(self._id)}".encode()).hexdigest(), 16) % (2**32)
        self.random_generator.seed(seed)

    def get_random_generator(self):
        return self.random_generator

    def run(self,tick,arena_shape,objects,agents):
        pass

class StaticObject(Object):
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        super().__init__(entity_type,config_elem,_id)
        if config_elem.get("shape") in ("circle","square","rectangle"):
            self.shape_type = "flat"
        elif config_elem.get("shape") in ("sphere","cube","cuboid","cylinder"):
            self.shape_type = "dense"
        else: raise ValueError(f"Invalid object type: {self.entity_type}")
        self.shape = Shape3DFactory.create_shape("object",config_elem.get("shape","point"), {key:val for key,val in config_elem.items()})
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.start_position = Vector3D()
        self.start_orientation = Vector3D()
        temp_strength = config_elem.get("strength", [10])
        if temp_strength != None:
            try:
                self.strength = temp_strength[_id]
            except:
                self.strength = temp_strength[-1]
        temp_uncertainty = config_elem.get("uncertainty", [0])
        if temp_uncertainty != None:
            try:
                self.uncertainty = temp_uncertainty[_id]
            except:
                self.uncertainty = temp_uncertainty[-1]
        temp_position = config_elem.get("position", None)
        if temp_position != None:
            self.position_from_dict = True
            try:
                self.start_position = Vector3D(temp_position[_id][0],temp_position[_id][1],temp_position[_id][2])
            except:
                self.start_position = Vector3D(temp_position[-1][0],temp_position[-1][1],temp_position[-1][2])
        temp_orientation = config_elem.get("orientation", None)
        if temp_orientation != None:
            self.orientation_from_dict = True
            try:
                self.start_orientation = Vector3D(temp_orientation[_id][0],temp_orientation[_id][1],temp_orientation[_id][2])
            except:
                self.start_orientation = Vector3D(temp_orientation[-1][0],temp_orientation[-1][1],temp_orientation[-1][2])
            self.orientation = self.start_orientation

    def to_origin(self):
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.shape.center = self.position
        self.shape.set_vertices()

    def set_start_position(self,new_position:Vector3D,_translate:bool = True):
        self.start_position = new_position
        self.set_position(new_position,_translate)

    def set_position(self,new_position:Vector3D,_translate:bool = True):
        self.position = new_position
        if _translate: self.shape.translate(self.position)

    def set_start_orientation(self,new_orientation:Vector3D):
        self.start_orientation = new_orientation
        self.set_orientation(new_orientation)

    def set_orientation(self,new_orientation:Vector3D):
        self.orientation = new_orientation
        self.shape.rotate(self.start_orientation.z)

    def get_start_position(self):
        return self.start_position
    
    def get_start_orientation(self):
        return self.start_orientation
    
    def get_position(self):
        return self.position

    def get_orientation(self):
        return self.orientation
    
    def get_strength(self):
        return self.strength

    def get_uncertainty(self):
        return self.uncertainty
        
    def close(self):
        del self.shape

    def get_shape(self):
        return self.shape

    def get_shape_type(self):
        return self.shape_type
    
class StaticAgent(Agent):
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        super().__init__(entity_type,config_elem,_id)
        if config_elem.get("shape") in ("sphere","cube","cuboid","cylinder"):
            self.shape_type = "dense"
        self.shape = Shape3DFactory.create_shape("agent",config_elem.get("shape","point"), {key:val for key,val in config_elem.items()})
        self.shape.add_attachment(Shape3DFactory.create_shape("mark","circle", {"_id":"idle", "color":"red", "diameter":0.01}))
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.start_position = Vector3D()
        self.start_orientation = Vector3D()
        temp_position = config_elem.get("position", None)
        if temp_position != None:
            self.position_from_dict = True
            try:
                self.start_position = Vector3D(temp_position[0],temp_position[1],temp_position[2])
            except:
                self.start_position = Vector3D(temp_position[-1][0],temp_position[-1][1],temp_position[-1][2])
        temp_orientation = config_elem.get("orientation", None)
        if temp_orientation != None:
            self.orientation_from_dict = True
            try:
                self.start_orientation = Vector3D(temp_orientation[0],temp_orientation[1],temp_orientation[2])
            except:
                self.start_orientation = Vector3D(temp_orientation[-1][0],temp_orientation[-1][1],temp_orientation[-1][2])
            self.orientation = self.start_orientation

    def to_origin(self):
        self.position = Vector3D()
        self.shape.center = self.position
        self.shape.set_vertices()

    def set_start_position(self,new_position:Vector3D,_translate:bool = True):
        self.start_position = new_position
        self.set_position(new_position,_translate)

    def set_position(self,new_position:Vector3D,_translate:bool = True):
        self.position = new_position
        if _translate:
            self.shape.translate(self.position)

    def set_start_orientation(self,new_orientation:Vector3D):
        self.start_orientation = new_orientation
        self.set_orientation(new_orientation)

    def set_orientation(self,new_orientation:Vector3D):
        self.orientation = new_orientation
        self.shape.rotate(self.start_orientation.z)

    def get_start_position(self):
        return self.start_position
    
    def get_start_orientation(self):
        return self.start_orientation
    
    def get_position(self):
        return self.position

    def get_orientation(self):
        return self.orientation

    def close(self):
        del self.shape

    def get_shape(self):
        return self.shape

    def get_shape_type(self):
        return self.shape_type
    
class MovableObject(StaticObject):
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        super().__init__(entity_type,config_elem,_id)

class MovableAgent(StaticAgent):

    STOP    = 0
    FORWARD = 1
    LEFT    = 2
    RIGHT   = 3

    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        super().__init__(entity_type,config_elem,_id)
        self.config_elem = config_elem
        self.max_absolute_velocity = float(config_elem.get("linear_velocity",0.01)) / self.ticks_per_second
        self.max_angular_velocity = int(config_elem.get("angular_velocity",360)) / self.ticks_per_second
        self.forward_vector = Vector3D()
        self.goal_position = None
        self.prev_orientation = Vector3D()
        self.position = Vector3D()
        self.prev_position = Vector3D()
        self.prev_goal_distance = 0
        self.detection = config_elem.get("detection","GPS")
        self.moving_behavior = config_elem.get("moving_behavior","random_walk")
        self.pre_run = False

        if self.moving_behavior == "spin_model":
            self.spin_model_params = config_elem.get("spin_model", {})
            self.spin_pre_run_steps = self.spin_model_params.get("spin_pre_run_steps",0)
            self.pre_run = True if self.spin_pre_run_steps > 0 else False
            self.spin_per_tick = self.spin_model_params.get("spin_per_tick", 3)
            self.perception_width = self.spin_model_params.get("perception_width",0.5)
            self.num_groups = self.spin_model_params.get("num_groups",32)
            self.num_spins_per_group = self.spin_model_params.get("num_spins_per_group",10)
            self.perception_global_inhibition = self.spin_model_params.get("perception_global_inhibition",0)
            self.task = self.spin_model_params.get("task","selection")
            self.reference = self.spin_model_params.get("reference","egocentric")
            self.group_angles = np.linspace(0, 2 * _PI, self.num_groups, endpoint=False)
        else:
            self.pre_run = False
            self.max_turning_ticks = 160
            self.standard_motion_steps = 5*16
            self.crw_exponent = config_elem.get("crw_exponent",1)
            self.levy_exponent = config_elem.get("levy_exponent",1.75)

    def reset(self):
        if self.moving_behavior == "spin_model":
            self.perception = None
            self.spin_system = SpinSystem(
                self.random_generator,
                self.num_groups,
                self.num_spins_per_group,
                float(self.spin_model_params.get("T",0.1)),
                float(self.spin_model_params.get("J",1)),
                float(self.spin_model_params.get("nu",0)),
                float(self.spin_model_params.get("p_spin_up",0.5)),
                int(self.spin_model_params.get("time_delay",1)),
                self.spin_model_params.get("dynamics","metropolis")
            )
        else:
            self.turning_ticks = 0
            self.forward_ticks = 0
            self.motion = MovableAgent.STOP
            self.last_motion_tick = 0

    def get_spin_system_data(self):
        if self.moving_behavior == "spin_model":
            return self.spin_system.get_states(),self.spin_system.get_angles(),self.spin_system.get_external_field(),self.spin_system.get_avg_direction_of_activity()
        return None
    
    def get_max_absolute_velocity(self):
        return self.max_absolute_velocity
    
    def get_prev_position(self):
        return self.prev_position
    
    def get_prev_orientation(self):
        return self.prev_orientation
    
    def get_position(self):
        return self.position
    
    def get_orientation(self):
        return self.orientation
    
    def get_forward_vector(self):
        return self.forward_vector

    def set_start_orientation(self,new_orientation:Vector3D):
        super().set_start_orientation(new_orientation)
        
    def set_orientation(self,new_orientation:Vector3D):
        super().set_orientation(new_orientation)

    def random_walk(self,tick):
        if self.motion == MovableAgent.LEFT or self.motion == MovableAgent.RIGHT or self.motion == MovableAgent.STOP:
            if tick > self.last_motion_tick + self.turning_ticks:
                self.last_motion_tick = tick
                self.motion = MovableAgent.FORWARD
                self.forward_ticks = abs(levy(self.random_generator,self.standard_motion_steps,self.levy_exponent))
        elif self.motion == MovableAgent.FORWARD:
            if tick > self.last_motion_tick + self.forward_ticks:
                self.last_motion_tick = tick
                p = Random.uniform(self.random_generator,0,1)
                if p < 0.5: self.motion = MovableAgent.LEFT
                else: self.motion = MovableAgent.RIGHT
                angle = Random.uniform(self.random_generator,0,_PI) if self.crw_exponent == 0 else abs(wrapped_cauchy_pp(self.random_generator,self.crw_exponent))
                self.turning_ticks = int(angle * self.max_turning_ticks)

    def random_way_point(self, arena_shape):
        if self.goal_position is None or (self.position - self.goal_position).magnitude() <= .001:
            self.goal_position = self.shape._get_random_point_inside_shape(self.random_generator, arena_shape)
        dx = self.goal_position.x - self.position.x
        dy = self.goal_position.y - self.position.y
        angle_to_goal = math.degrees(math.atan2(-dy, dx))
        angle_to_goal = normalize_angle(angle_to_goal - self.orientation.z)
        distance = self.position - self.goal_position
        dist_mag = distance.magnitude()
        if abs(dist_mag) >= self.prev_goal_distance:
            self.last_motion_tick += 1
        self.prev_goal_distance = dist_mag
        if self.last_motion_tick > self.ticks_per_second:
            self.last_motion_tick = 0
            self.goal_position = None
        if angle_to_goal >= self.max_angular_velocity:
            self.motion = MovableAgent.LEFT
        elif angle_to_goal <= -self.max_angular_velocity:
            self.motion = MovableAgent.RIGHT
        else:
            self.motion = MovableAgent.FORWARD

    def post_step(self,position_correction):
        if position_correction != None:
            self.position = position_correction
            self.shape.translate(self.position)
            self.shape.translate_attachments(self.orientation.z)
    
    def spin_pre_run(self,objects,agents):
        if self.pre_run:
            self.update_detection(objects,agents)
            for _ in range(self.spin_pre_run_steps):
                self.spin_system.step(timedelay=False)
            self.spin_system.set_p_spin_up(np.mean(self.spin_system.get_states()))
            self.spin_system.reset_spins()

    def update_detection(self, objects, agents):
        perception = np.zeros(self.num_groups * self.num_spins_per_group)
        sigma0 = self.perception_width
        if self.task == "flocking":
            for club, agent_shapes in agents.items():
                for n in range(len(agent_shapes)):
                    if club+"_"+str(n)==self.get_name(): continue
                    agent_pos = agent_shapes[n].center_of_mass()
                    dx = agent_pos.x - self.position.x
                    dy = agent_pos.y - self.position.y
                    angle_to_object = math.degrees(math.atan2(-dy, dx))
                    if self.reference == "egocentric":
                        angle_to_object = angle_to_object - self.orientation.z
                    angle_to_object = normalize_angle(angle_to_object)
                    effective_width = sigma0
                    angle_diffs = np.abs(self.group_angles - math.radians(angle_to_object))
                    angle_diffs = np.minimum(angle_diffs, 2 * _PI - angle_diffs)
                    sigma = max(effective_width, 1e-6)
                    weights = (sigma0 / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
                    weights *= 5
                    perception += np.repeat(weights, self.num_spins_per_group)
        elif self.task == "selection":
            for _, (shapes, positions, strengths, uncertainties) in objects.items():
                for n in range(len(shapes)):
                    dx = positions[n].x - self.position.x
                    dy = positions[n].y - self.position.y
                    angle_to_object = math.degrees(math.atan2(-dy, dx))
                    if self.reference == "egocentric":
                        angle_to_object = angle_to_object - self.orientation.z
                    angle_to_object = normalize_angle(angle_to_object)
                    effective_width = sigma0 + uncertainties[n]
                    angle_diffs = np.abs(self.group_angles - math.radians(angle_to_object))
                    angle_diffs = np.minimum(angle_diffs, 2 * _PI - angle_diffs)
                    sigma = max(effective_width, 1e-6)
                    weights = (sigma0 / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
                    weights *= strengths[n]
                    perception += np.repeat(weights, self.num_spins_per_group)
        perception -= self.perception_global_inhibition
        self.perception = perception

    def run(self,tick,arena_shape,objects,agents):
        if self.detection == "visual":
            self.spins_routine(objects,agents)
        elif self.detection == "GPS":
            self.GPS_routine(tick,arena_shape)
        self.position = self.position + self.forward_vector
        self.shape.rotate(self.delta_orientation.z)
        self.shape.translate(self.position)
        self.shape.translate_attachments(self.orientation.z)

    def spins_routine(self, objects, agents):
        self.prev_position = self.position
        self.prev_orientation = self.orientation
        self.update_detection(objects,agents)
        self.spin_system.update_external_field(self.perception)
        self.spin_system.run_spins(steps=self.spin_per_tick)
        angle_rad = self.spin_system.average_direction_of_activity()
        if angle_rad is not None:
            if self.reference == "allocentric":
                angle_rad = angle_rad - math.radians(self.orientation.z)
            angle_deg = normalize_angle(math.degrees(angle_rad))
            angle_deg = max(min(angle_deg, self.max_angular_velocity), -self.max_angular_velocity)
            self.delta_orientation = Vector3D(0, 0, angle_deg)
            self.orientation = self.orientation + self.delta_orientation
            self.orientation.z = normalize_angle(self.orientation.z)
            angle_rad = math.radians(self.orientation.z)
            width = self.spin_system.get_width_of_activity()
            scaling_factor = 1.0 / width if width and width > 0 else 0.0
            scaling_factor = np.clip(scaling_factor, 0.0, 1.0)
            cos_angle = math.cos(angle_rad)
            sin_angle = math.sin(angle_rad)
            self.forward_vector = Vector3D(
                self.max_absolute_velocity * scaling_factor * cos_angle,
                self.max_absolute_velocity * scaling_factor * -sin_angle,
                0
            )

    def GPS_routine(self, tick, arena_shape):
        if self.moving_behavior == "random_walk":
            self.random_walk(tick)
        elif self.moving_behavior == "random_way_point":
            self.random_way_point(arena_shape)
        else:
            raise ValueError(f"Invalid moving behavior: {self.moving_behavior}")
        self.prev_position = self.position
        self.prev_orientation = self.orientation
        self.delta_orientation = Vector3D(0, 0, 0)
        if self.motion == MovableAgent.LEFT:
            self.delta_orientation.z = self.max_angular_velocity
        elif self.motion == MovableAgent.RIGHT:
            self.delta_orientation.z = -self.max_angular_velocity
        self.orientation = self.orientation + self.delta_orientation
        self.orientation.z = normalize_angle(self.orientation.z)
        angle_rad = math.radians(self.orientation.z)
        cos_angle = math.cos(angle_rad)
        sin_angle = math.sin(angle_rad)
        self.forward_vector = Vector3D(
            self.max_absolute_velocity * cos_angle,
            self.max_absolute_velocity * -sin_angle,
            0
        )
    
    def close(self):
        return super().close()
    
def normalize_angle(angle: float):
    """Normalize the angle between -180 e 180 degrees."""
    return ((angle + 180) % 360) - 180

def exponential_distribution(random_generator, alpha):
    u = Random.uniform(random_generator, 0, 1)
    return -alpha * math.log1p(-u)

def wrapped_cauchy_pp(random_generator, c: float) -> float:
    q = 0.5
    u = Random.uniform(random_generator, 0, 1)
    val = (1 - c) / (1 + c)
    return 2 * math.atan(val * math.tanh(_PI * (u - q)))

def levy(random_generator, c: float, alpha: float) -> int:
    u = _PI * (Random.uniform(random_generator, 0, 1) - 0.5)
    if alpha == 1:
        return int(c * math.tan(u))
    v = 0
    while v == 0:
        v = exponential_distribution(random_generator, 1)
    if alpha == 2:
        return int(c * 2 * math.sin(u) * math.sqrt(v))
    t = math.sin(alpha * u) / math.pow(math.cos(u), 1 / alpha)
    s = math.pow(math.cos((1 - alpha) * u) / v, (1 - alpha) / alpha)
    return int(c * t * s)

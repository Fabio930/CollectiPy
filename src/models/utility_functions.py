# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math
from random import Random

_PI = math.pi

def normalize_angle(angle: float) -> float:
    """Normalize an angle between -180 and 180 degrees."""
    return ((angle + 180) % 360) - 180

def exponential_distribution(random_generator: Random, alpha: float) -> float:
    """Exponential distribution."""
    u = random_generator.random()
    return -alpha * math.log1p(-u)

def wrapped_cauchy_pp(random_generator: Random, c: float) -> float:
    """Wrapped cauchy pp."""
    q = 0.5
    u = random_generator.random()
    val = (1 - c) / (1 + c)
    return 2 * math.atan(val * math.tanh(_PI * (u - q)))

def levy(random_generator: Random, c: float, alpha: float) -> int:
    """Sample the operation."""
    rng_uniform = random_generator.uniform
    u = _PI * (rng_uniform(0, 1) - 0.5)
    if alpha == 1:
        return int(c * math.tan(u))
    v = 0.0
    while v == 0.0:
        v = exponential_distribution(random_generator, 1)
    if alpha == 2:
        return int(c * 2 * math.sin(u) * math.sqrt(v))
    t = math.sin(alpha * u) / math.pow(math.cos(u), 1 / alpha)
    s = math.pow(math.cos((1 - alpha) * u) / v, (1 - alpha) / alpha)
    return int(c * t * s)

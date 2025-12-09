# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math

class Vector3D:
    """Vector 3 d."""
    def __init__(self, x:float=0, y:float=0, z:float=0):
        """Initialize the instance."""
        self.x = x
        self.y = y
        self.z = z

    def __add__(self, other):
        """Provide the add."""
        return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        """Provide the sub."""
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar):
        """Provide the mul."""
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)

    def __truediv__(self, scalar):
        """Provide the truediv."""
        return Vector3D(self.x / scalar, self.y / scalar, self.z / scalar)

    def dot(self, other):
        """Provide the dot."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other):
        """Provide the cross."""
        return Vector3D(self.y * other.z - self.z * other.y,
                        self.z * other.x - self.x * other.z,
                        self.x * other.y - self.y * other.x)

    def magnitude(self):
        """Provide the magnitude."""
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalize(self):
        """Normalize the vector."""
        mag = self.magnitude()
        if mag == 0:
            return Vector3D()
        return self / mag

    def v_rotate_z(self, point, angle:float):
        """Rotate the vector around ``point`` on the Z axis."""
        translated = self - point
        cos_theta = math.cos(angle)
        sin_theta = math.sin(angle)
        x = translated.x * cos_theta - translated.y * sin_theta
        y = translated.x * sin_theta + translated.y * cos_theta
        rotated = Vector3D(x, y, translated.z)
        return rotated + point

    def __repr__(self) -> str:
        """Return the string representation."""
        return f"Vector3D({self.x}, {self.y}, {self.z})"

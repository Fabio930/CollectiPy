# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

from collections import defaultdict

class SpatialGrid:
    """Spatial grid."""
    def __init__(self, cell_size):
        """Initialize the instance."""
        self.cell_size = cell_size
        self.grid = defaultdict(list)

    def _cell_coords(self, pos):
        """Cell coords."""
        return (int(pos.x // self.cell_size), int(pos.y // self.cell_size))

    def clear(self):
        """Clear the stored data."""
        self.grid.clear()

    def insert(self, agent):
        """Insert the provided entry."""
        cell = self._cell_coords(agent.get_position())
        self.grid[cell].append(agent)

    def neighbors(self, agent, radius):
        """Return the operation."""
        pos = agent.get_position()
        cell_x, cell_y = self._cell_coords(pos)
        neighbors = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                cell = (cell_x + dx, cell_y + dy)
                for other in self.grid.get(cell, []):
                    if other is not agent:
                        if (other.get_position() - pos).magnitude() <= radius:
                            neighbors.append(other)
        return neighbors
    
    def close(self):
        """Close the component resources."""
        del self.grid, self.cell_size
        return

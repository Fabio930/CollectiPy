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
        """Insert the provided entry (its position is read once, here)."""
        pos = agent.get_position()
        self.grid[self._cell_coords(pos)].append((pos.x, pos.y, pos.z, agent))

    def neighbors(self, agent, radius):
        """Return the entries of the adjacent cells within `radius` of `agent`."""
        pos = agent.get_position()
        px, py, pz = pos.x, pos.y, pos.z
        cell_x, cell_y = self._cell_coords(pos)
        radius_sq = radius * radius
        grid = self.grid
        neighbors = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for x, y, z, other in grid.get((cell_x + dx, cell_y + dy), ()):
                    if other is not agent and (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2 <= radius_sq:
                        neighbors.append(other)
        return neighbors
    
    def close(self):
        """Close the component resources."""
        del self.grid, self.cell_size
        return

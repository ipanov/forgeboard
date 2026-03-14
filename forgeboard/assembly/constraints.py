"""Assembly constraint types for ForgeBoard.

Each constraint captures a geometric relationship between two interface points
on different parts.  The ``solve`` method computes the :class:`Placement` that
satisfies the constraint, given the current position of one part and the
available interfaces on the other.

Constraint hierarchy
--------------------
``Constraint`` (abstract base)
  |-- ``Mate``    -- face-to-face contact (normals flipped to oppose)
  |-- ``Flush``   -- coplanar surfaces (normals aligned, no flip)
  |-- ``Align``   -- coaxial alignment (axes coincident)
  |-- ``Offset``  -- fixed translation along a direction
  |-- ``Angle``   -- angular relationship between two interfaces
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from forgeboard.core.types import (
    AXIS_Z,
    ORIGIN,
    InterfacePoint,
    Placement,
    Vector3,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rotation_between(src: Vector3, dst: Vector3) -> tuple[Vector3, float]:
    """Compute the axis and angle (degrees) to rotate *src* onto *dst*.

    Both vectors must be unit-length.  Returns ``(axis, angle_deg)``.
    When the vectors are (anti-)parallel, falls back to a perpendicular axis.
    """
    dot = src.dot(dst)
    # Clamp for numerical safety
    dot = max(-1.0, min(1.0, dot))

    if dot > 1.0 - 1e-9:
        # Already aligned -- identity rotation
        return (AXIS_Z, 0.0)

    if dot < -1.0 + 1e-9:
        # Opposite -- rotate 180 around any perpendicular axis
        perp = src.cross(AXIS_Z)
        if perp.length() < 1e-9:
            perp = src.cross(Vector3(x=1.0, y=0.0, z=0.0))
        return (perp.normalized(), 180.0)

    axis = src.cross(dst).normalized()
    angle_rad = math.acos(dot)
    return (axis, math.degrees(angle_rad))


def _apply_rotation_to_point(
    point: Vector3,
    axis: Vector3,
    angle_deg: float,
) -> Vector3:
    """Rotate *point* around *axis* (through the origin) by *angle_deg*."""
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    k = axis.normalized()
    # Rodrigues' rotation formula
    return point * cos_a + k.cross(point) * sin_a + k * (k.dot(point)) * (1.0 - cos_a)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Constraint(ABC):
    """Abstract base for assembly constraints.

    Parameters
    ----------
    interface_a : str
        Name of the interface on part A.
    interface_b : str
        Name of the interface on part B.
    """

    def __init__(self, interface_a: str, interface_b: str) -> None:
        self.interface_a = interface_a
        self.interface_b = interface_b

    @abstractmethod
    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        """Compute the placement for part B that satisfies this constraint.

        Parameters
        ----------
        part_a_placement : Placement
            Current world-space placement of part A.
        part_a_interface : InterfacePoint
            The mating interface on part A (in part-A local coordinates).
        part_b_interface : InterfacePoint
            The mating interface on part B (in part-B local coordinates).

        Returns
        -------
        Placement
            The world-space placement to apply to part B.
        """
        ...

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"interface_a={self.interface_a!r}, "
            f"interface_b={self.interface_b!r})"
        )


# ---------------------------------------------------------------------------
# Mate -- face-to-face contact
# ---------------------------------------------------------------------------

class Mate(Constraint):
    """Face-to-face contact constraint.

    Aligns two interface points so that their normals point in opposite
    directions (face-to-face contact) and the positions coincide.
    """

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        # Target normal for B's interface: opposite of A's interface normal
        target_normal = -part_a_interface.normal

        # Rotation to align B's normal onto the target
        rot_axis, rot_angle = _rotation_between(
            part_b_interface.normal, target_normal
        )

        # After rotating part B, its interface point moves.  Compute where
        # the B interface position ends up, then translate so it coincides
        # with A's interface position (offset by A's placement).
        rotated_b_pos = _apply_rotation_to_point(
            part_b_interface.position, rot_axis, rot_angle
        )

        # A's interface in world space
        a_world = part_a_placement.position + part_a_interface.position
        # Translation needed so B's rotated interface lands on A's
        translation = a_world - rotated_b_pos

        return Placement(
            position=translation,
            rotation_axis=rot_axis,
            rotation_angle_deg=rot_angle,
        )


# ---------------------------------------------------------------------------
# Flush -- coplanar surfaces
# ---------------------------------------------------------------------------

class Flush(Constraint):
    """Coplanar surface constraint.

    Like ``Mate`` but normals are aligned (same direction) rather than
    opposed.  Useful for mounting surfaces that face the same way.
    """

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        # Target: B normal matches A normal (not flipped)
        target_normal = part_a_interface.normal

        rot_axis, rot_angle = _rotation_between(
            part_b_interface.normal, target_normal
        )

        rotated_b_pos = _apply_rotation_to_point(
            part_b_interface.position, rot_axis, rot_angle
        )

        a_world = part_a_placement.position + part_a_interface.position
        translation = a_world - rotated_b_pos

        return Placement(
            position=translation,
            rotation_axis=rot_axis,
            rotation_angle_deg=rot_angle,
        )


# ---------------------------------------------------------------------------
# Align -- coaxial alignment
# ---------------------------------------------------------------------------

class Align(Constraint):
    """Coaxial alignment constraint.

    Aligns the *axis* vectors of two cylindrical interfaces so they are
    collinear, then positions them so the interface points coincide.
    """

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        # For cylindrical interfaces the normal *is* the axis direction.
        # Use the normal vector as the alignment axis for both parts.
        a_axis = part_a_interface.normal.normalized()
        b_axis = part_b_interface.normal.normalized()

        rot_axis, rot_angle = _rotation_between(b_axis, a_axis)

        rotated_b_pos = _apply_rotation_to_point(
            part_b_interface.position, rot_axis, rot_angle
        )

        a_world = part_a_placement.position + part_a_interface.position
        translation = a_world - rotated_b_pos

        return Placement(
            position=translation,
            rotation_axis=rot_axis,
            rotation_angle_deg=rot_angle,
        )


# ---------------------------------------------------------------------------
# Offset -- fixed distance along a direction
# ---------------------------------------------------------------------------

class Offset(Constraint):
    """Fixed-distance offset constraint.

    After aligning as a ``Mate``, applies an additional offset along the
    interface normal direction.

    Parameters
    ----------
    interface_a : str
        Name of the interface on part A.
    interface_b : str
        Name of the interface on part B.
    distance_mm : float
        Offset distance in millimetres along the interface-A normal.
    """

    def __init__(
        self,
        interface_a: str,
        interface_b: str,
        distance_mm: float = 0.0,
    ) -> None:
        super().__init__(interface_a, interface_b)
        self.distance_mm = distance_mm

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        # Start from a Mate solution, then shift by the offset distance
        mate = Mate(self.interface_a, self.interface_b)
        base_placement = mate.solve(
            part_a_placement, part_a_interface, part_b_interface
        )

        offset_dir = part_a_interface.normal.normalized()
        shift = offset_dir * self.distance_mm

        return Placement(
            position=base_placement.position + shift,
            rotation_axis=base_placement.rotation_axis,
            rotation_angle_deg=base_placement.rotation_angle_deg,
        )

    def __repr__(self) -> str:
        return (
            f"Offset(interface_a={self.interface_a!r}, "
            f"interface_b={self.interface_b!r}, "
            f"distance_mm={self.distance_mm})"
        )


# ---------------------------------------------------------------------------
# Angle -- angular relationship
# ---------------------------------------------------------------------------

class Angle(Constraint):
    """Angular relationship constraint.

    Positions part B at a specified angle relative to part A's interface
    normal, rotating around a given axis (defaults to the interface normal
    cross product, i.e. the hinge axis).

    Parameters
    ----------
    interface_a : str
        Name of the interface on part A.
    interface_b : str
        Name of the interface on part B.
    angle_deg : float
        Angle in degrees between the two interface normals.
    hinge_axis : Vector3 | None
        Axis of rotation.  When *None*, computed as the cross product of
        the two interface normals (or falls back to AXIS_Z).
    """

    def __init__(
        self,
        interface_a: str,
        interface_b: str,
        angle_deg: float = 0.0,
        hinge_axis: Optional[Vector3] = None,
    ) -> None:
        super().__init__(interface_a, interface_b)
        self.angle_deg = angle_deg
        self.hinge_axis = hinge_axis

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        # Determine the hinge axis
        if self.hinge_axis is not None:
            h_axis = self.hinge_axis.normalized()
        else:
            cross = part_a_interface.normal.cross(part_b_interface.normal)
            if cross.length() < 1e-9:
                # Parallel normals -- pick a perpendicular axis
                cross = part_a_interface.normal.cross(AXIS_Z)
                if cross.length() < 1e-9:
                    cross = part_a_interface.normal.cross(Vector3(x=1.0, y=0.0, z=0.0))
            h_axis = cross.normalized()

        # Rotate B's interface normal by the specified angle around the hinge
        # axis, then compute the placement to achieve that orientation.
        target_normal = _apply_rotation_to_point(
            part_a_interface.normal, h_axis, self.angle_deg
        )

        rot_axis, rot_angle = _rotation_between(
            part_b_interface.normal, target_normal
        )

        rotated_b_pos = _apply_rotation_to_point(
            part_b_interface.position, rot_axis, rot_angle
        )

        a_world = part_a_placement.position + part_a_interface.position
        translation = a_world - rotated_b_pos

        return Placement(
            position=translation,
            rotation_axis=rot_axis,
            rotation_angle_deg=rot_angle,
        )

    def __repr__(self) -> str:
        return (
            f"Angle(interface_a={self.interface_a!r}, "
            f"interface_b={self.interface_b!r}, "
            f"angle_deg={self.angle_deg})"
        )

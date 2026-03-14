# Assembly Guide

This document explains how to define, build, solve, validate, and export
assemblies in ForgeBoard.

## Overview

An assembly in ForgeBoard is a collection of parts positioned relative to
each other by geometric constraints. The workflow is:

1. Create an `Assembly` (mutable builder)
2. Add parts with their interface definitions
3. Define constraints between interface pairs
4. Call `solve()` to compute placements
5. Inspect collision/clearance reports
6. Run validation checks
7. Export results (STEP, STL, SVG, BOM)

## Creating an Assembly

```python
from forgeboard.assembly.orchestrator import Assembly

asm = Assembly("DeskLamp")
```

The name is used in exports and reports.

## Adding Parts

Each part needs a name, a geometry `Shape` (from the CAD engine), and
optionally a set of interfaces and constraints.

```python
from forgeboard.engines.build123d_engine import Build123dEngine
from forgeboard.core.types import InterfacePoint, InterfaceType, Vector3

engine = Build123dEngine()

# Create geometry
base_shape = engine.create_cylinder(radius=75, height=8)
arm_shape = engine.create_cylinder(radius=6, height=350)

# Define interfaces
base_interfaces = {
    "arm_socket": InterfacePoint(
        name="arm_socket",
        position=Vector3(x=0, y=0, z=8),
        normal=Vector3(x=0, y=0, z=1),
        type=InterfaceType.CYLINDRICAL,
        diameter_mm=12.5,
    ),
}

arm_interfaces = {
    "base_insert": InterfacePoint(
        name="base_insert",
        position=Vector3(x=0, y=0, z=0),
        normal=Vector3(x=0, y=0, z=-1),
        type=InterfaceType.CYLINDRICAL,
        diameter_mm=12.0,
    ),
    "head_mount": InterfacePoint(
        name="head_mount",
        position=Vector3(x=0, y=0, z=350),
        normal=Vector3(x=0, y=0, z=1),
        type=InterfaceType.CYLINDRICAL,
        diameter_mm=10.0,
    ),
}

# Add parts to assembly
asm.add_part("base", base_shape, at_origin=True, interfaces=base_interfaces)
```

The first part should have `at_origin=True` -- it serves as the assembly
datum and gets an identity placement (no translation, no rotation).

## Defining Constraints

Constraints are added either inline (when adding a part) or explicitly
between two named parts.

### Inline Constraints

```python
from forgeboard.assembly.constraints import Mate, Align

asm.add_part(
    "arm",
    arm_shape,
    interfaces=arm_interfaces,
    constraints=[Align("arm_socket", "base_insert")],
)
```

When adding a part with inline constraints, ForgeBoard searches
previously-added parts for the matching interface name (`"arm_socket"`)
and uses that part as the reference.

### Explicit Constraints

```python
asm.add_part("arm", arm_shape, interfaces=arm_interfaces)
asm.add_constraint("base", "arm", Align("arm_socket", "base_insert"))
```

This form names both parts explicitly. Use it when the auto-detection
is ambiguous (e.g., multiple parts have the same interface name).

## Constraint Types

ForgeBoard provides five constraint types. Each takes the name of an
interface on part A and an interface on part B.

### Mate

Face-to-face contact. The interface normals are flipped to point in
opposite directions, and the interface positions are made coincident.

```
    Part A              Part B
  +--------+         +--------+
  |        |         |        |
  |   A.n->|  <-B.n  |        |
  |        |=========|        |     <- surfaces touching
  +--------+         +--------+
```

Use Mate when two flat faces press against each other: a plate sitting
on a bracket, a lid closing on a housing.

```python
from forgeboard.assembly.constraints import Mate

Mate("top_face", "bottom_face")
```

### Flush

Coplanar surfaces. Like Mate, but the normals point in the same direction
instead of opposing. The interface positions still coincide.

```
  +--------+   +--------+
  |        |   |        |
  |   A.n->|   |   B.n->|     <- normals same direction
  |========|   |========|     <- surfaces in the same plane
  +--------+   +--------+
```

Use Flush for parts that sit side-by-side on the same surface plane.

```python
from forgeboard.assembly.constraints import Flush

Flush("mounting_face", "mounting_face")
```

### Align

Coaxial alignment. The axis vectors of two cylindrical interfaces are
made collinear, and the interface positions coincide.

```
        +---+
        | B |
        | | |     <- B's axis
   +----|---|----+
   |    | | |    |
   |    | A |    |     <- A's axis (same line)
   |    | | |    |
   +----|---|----+
        +---+
```

Use Align for shafts through bearings, tubes inserted into bores, pins
in holes.

```python
from forgeboard.assembly.constraints import Align

Align("bore", "shaft")
```

### Offset

A Mate constraint plus a fixed distance along the normal direction. The
parts are face-to-face with a gap between them.

```
  +--------+
  |   A    |
  |   A.n->|
  +--------+
       |
       | distance_mm
       |
  +--------+
  |   B    |
  +--------+
```

Use Offset for gaskets, spacers, or any situation where parts need a
specific gap.

```python
from forgeboard.assembly.constraints import Offset

Offset("top_face", "bottom_face", distance_mm=2.5)
```

### Angle

Angular relationship between two interface normals. Part B is positioned
at a specified angle relative to part A's interface, rotating around a
hinge axis.

```
       A
       |
       |  angle_deg
       | /
       |/
       +--------B
```

Use Angle for hinges, adjustable joints, tilted mounting brackets.

```python
from forgeboard.assembly.constraints import Angle
from forgeboard.core.types import Vector3

Angle("hinge_a", "hinge_b", angle_deg=45.0)
Angle("pivot", "arm", angle_deg=90.0, hinge_axis=Vector3(x=1, y=0, z=0))
```

If `hinge_axis` is not provided, it is computed as the cross product of
the two interface normals.

## Solving the Assembly

```python
solved = asm.solve(
    engine,
    collision_tolerance_mm3=1.0,   # ignore intersections below 1 mm^3
    clearance_min_mm=0.2,          # require 0.2mm minimum gap
)
```

The solver processes parts in insertion order:

1. Parts with `at_origin=True` get identity placement.
2. All other parts are positioned by their constraints against
   already-placed parts.
3. After all parts are placed, pairwise collision detection runs.
4. Clearance checking runs.

The return value is a `SolvedAssembly` with:

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Assembly name |
| `parts` | `dict[str, SolvedPart]` | Map of part name to placement + shape |
| `collisions` | `list[Collision]` | Detected physical overlaps |
| `clearance_violations` | `list[ClearanceViolation]` | Parts too close together |
| `validation_report` | `ValidationReport` | Populated after `validate()` |
| `part_count` | `int` | Number of parts |
| `has_collisions` | `bool` | True if any collisions were found |
| `is_valid` | `bool` | True if no collisions and validation passed |

## Collision Detection

ForgeBoard uses a two-phase collision detection pipeline:

1. **AABB pre-filter**: Compute axis-aligned bounding boxes for all parts.
   Skip pairs whose boxes do not overlap.
2. **Exact boolean intersection**: For remaining candidates, compute the
   intersection volume using the CAD engine. Report pairs that exceed
   the tolerance threshold.

### Collision Severity Levels

| Severity | Volume Threshold | Meaning |
|----------|-----------------|---------|
| `MINOR` | 0 < vol < 10 mm^3 | Likely a tolerance issue or trivial interference. |
| `MAJOR` | 10 <= vol < 100 mm^3 | Real interference that needs attention. |
| `CRITICAL` | vol >= 100 mm^3 | Severe overlap -- parts cannot be physically assembled. |

```python
for c in solved.collisions:
    print(f"{c.part_a} <-> {c.part_b}: {c.volume_mm3:.1f} mm^3 ({c.severity.value})")
```

## Clearance Checking

Clearance checking verifies that all part pairs maintain a minimum air
gap. This is important for:

- Thermal clearance (heat dissipation)
- Electrical isolation
- Manufacturing tolerances
- Assembly/disassembly access

```python
for v in solved.clearance_violations:
    print(
        f"{v.part_a} <-> {v.part_b}: "
        f"gap={v.actual_gap_mm:.2f}mm (need {v.required_gap_mm:.2f}mm)"
    )
```

Negative `actual_gap_mm` values indicate overlapping parts.

## Validation

After solving, you can run additional validation checks using the
pipeline framework:

```python
from forgeboard.assembly.orchestrator import Assembly, ValidationPipeline
from forgeboard.core.types import ValidationResult, Severity

# Define a custom validation rule
def check_total_mass(solved, engine):
    total = Assembly.get_total_mass(solved, engine)
    if total > 5000:  # 5 kg budget
        return [ValidationResult(
            passed=False,
            severity=Severity.ERROR,
            message=f"Assembly mass {total:.0f}g exceeds 5000g budget",
            check_name="mass_budget",
        )]
    return [ValidationResult(
        passed=True,
        severity=Severity.INFO,
        message=f"Assembly mass {total:.0f}g within budget",
        check_name="mass_budget",
    )]

# Build and run the pipeline
pipeline = ValidationPipeline()
pipeline.add_rule(check_total_mass)
report = Assembly.validate(solved, pipeline, engine)

print(f"Passed: {report.passed}")
print(f"Errors: {report.error_count}")
print(f"Warnings: {report.warning_count}")
```

## Exporting Results

### STEP File

```python
Assembly.export(solved, engine, "output/assembly.step", fmt="step")
```

### STL Mesh

```python
Assembly.export(solved, engine, "output/assembly.stl", fmt="stl")
```

### SVG Render

```python
Assembly.export(solved, engine, "output/assembly_iso.svg", fmt="svg")
```

### Bill of Materials

```python
from forgeboard.core.registry import ComponentRegistry
from forgeboard.bom.generator import generate_bom
from forgeboard.bom.export import export_csv, export_json, export_markdown

registry = ComponentRegistry()
registry.load("my_assembly.yaml")

bom = generate_bom(solved, registry)

# Print summary
print(bom.summary())

# Export to files
export_csv(bom, "output/bom.csv")
export_json(bom, "output/bom.json")
export_markdown(bom, "output/bom.md")
```

## Aggregate Queries

The `Assembly` class provides static methods for querying a solved
assembly:

```python
# Overall bounding box
bbox = Assembly.get_bounding_box(solved, engine)
print(f"Size: {bbox.size_x:.1f} x {bbox.size_y:.1f} x {bbox.size_z:.1f} mm")

# Center of gravity
cog = Assembly.get_center_of_gravity(solved, engine)
print(f"CoG: ({cog.x:.1f}, {cog.y:.1f}, {cog.z:.1f})")

# Total mass
mass = Assembly.get_total_mass(solved, engine)
print(f"Total mass: {mass:.1f} g")
```

## Full Example: Desk Lamp

This example builds the desk lamp assembly described in the registry
example.

```python
from forgeboard.core.registry import ComponentRegistry
from forgeboard.assembly.orchestrator import Assembly
from forgeboard.assembly.constraints import Align, Mate
from forgeboard.engines.build123d_engine import Build123dEngine
from forgeboard.bom.generator import generate_bom
from forgeboard.bom.export import export_csv

# Load components from registry
registry = ComponentRegistry()
registry.load("forgeboard/schemas/registry_example.yaml")

# Create engine
engine = Build123dEngine()

# Create simplified geometry for each component
base_plate = engine.create_cylinder(radius=75, height=8)
arm = engine.create_cylinder(radius=6, height=350)
bracket = engine.create_box(80, 40, 1.5)
led = engine.create_cylinder(radius=17.5, height=16.6)

# Get interface definitions from registry
base_spec = registry.get("LAMP-MECH-001")
arm_spec = registry.get("LAMP-MECH-002")
bracket_spec = registry.get("LAMP-MECH-003")
led_spec = registry.get("LAMP-ELEC-001")

# Build assembly
asm = Assembly("DeskLamp")

asm.add_part("base_plate", base_plate,
    at_origin=True,
    interfaces=base_spec.interfaces,
)

asm.add_part("arm", arm,
    interfaces=arm_spec.interfaces,
    constraints=[Align("arm_socket", "base_insert")],
)

asm.add_part("bracket", bracket,
    interfaces=bracket_spec.interfaces,
    constraints=[Align("head_mount", "arm_clamp")],
)

asm.add_part("led", led,
    interfaces=led_spec.interfaces,
    constraints=[Mate("led_face", "bracket_mount")],
)

# Solve
solved = asm.solve(engine)

# Report
print(f"Parts: {solved.part_count}")
print(f"Collisions: {len(solved.collisions)}")
print(f"Clearance violations: {len(solved.clearance_violations)}")
print(f"Valid: {solved.is_valid}")

# Export
Assembly.export(solved, engine, "output/desk_lamp.step")
bom = generate_bom(solved, registry)
export_csv(bom, "output/desk_lamp_bom.csv")
print(bom.summary())
```

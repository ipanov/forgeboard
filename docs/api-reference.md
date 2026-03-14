# API Reference

Concise reference for ForgeBoard's public Python API. For detailed usage
and examples, see the other documentation files.

All lengths are in millimeters unless noted otherwise.

## Core Types

**Module:** `forgeboard.core.types`

### Vector3

3D point or direction vector. Frozen (immutable, hashable).

```python
from forgeboard.core.types import Vector3, ORIGIN, AXIS_X, AXIS_Y, AXIS_Z

v = Vector3(x=10.0, y=20.0, z=30.0)
v.length()                  # -> 37.416...
v.normalized()              # -> unit-length copy
v.dot(other)                # -> float
v.cross(other)              # -> Vector3
v.as_tuple()                # -> (10.0, 20.0, 30.0)
v + w                       # -> Vector3
v - w                       # -> Vector3
v * 2.0                     # -> Vector3
-v                          # -> Vector3
```

Constants: `ORIGIN`, `AXIS_X`, `AXIS_Y`, `AXIS_Z`.

### BoundingBox

Axis-aligned bounding box.

```python
from forgeboard.core.types import BoundingBox

bb = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=20, z_max=30)
# or
bb = BoundingBox(min_corner=Vector3(x=0, y=0, z=0), max_corner=Vector3(x=10, y=20, z=30))

bb.size_x                   # -> 10.0
bb.size_y                   # -> 20.0
bb.size_z                   # -> 30.0
bb.center                   # -> Vector3(5, 10, 15)
bb.volume                   # -> 6000.0
bb.overlaps(other)          # -> bool
bb.overlaps(other, margin=1.0)  # -> bool (expanded by margin)
bb.expanded(2.0)            # -> new BoundingBox, 2mm larger on each side
```

### InterfacePoint

Named connection point on a component.

```python
from forgeboard.core.types import InterfacePoint, InterfaceType

ipt = InterfacePoint(
    name="bolt_hole",
    position=Vector3(x=20, y=0, z=5),
    normal=Vector3(x=0, y=0, z=1),
    type=InterfaceType.CYLINDRICAL,
    diameter_mm=5.5,
    metadata={"note": "M5 clearance hole"},
)

ipt.flipped()               # -> copy with normal reversed
```

`InterfaceType` enum: `PLANAR`, `CYLINDRICAL`, `SPHERICAL`.

### Material

Physical material properties. Frozen.

```python
from forgeboard.core.types import Material

mat = Material(
    name="Aluminum_6061",
    density_g_cm3=2.70,
    yield_strength_mpa=276.0,
    thermal_conductivity=167.0,
    cost_per_kg=8.0,
    manufacturing_methods=["CNC milling", "extrusion"],
)
```

### ComponentSpec

Full specification of a single part.

```python
from forgeboard.core.types import ComponentSpec

spec = ComponentSpec(
    name="Base_Plate",
    id="PROJ-MECH-001",
    description="Flat aluminum mounting plate",
    category="structure",
    material=mat,
    dimensions={"length_mm": 80, "width_mm": 60, "thickness_mm": 5},
    interfaces={"top_face": ipt},
    mass_g=65.0,
    is_cots=False,
    procurement={"unit_cost": 15.0, "supplier": "SendCutSend"},
    metadata={},
)
```

### BOMEntry

Single line item in a bill of materials. Frozen.

```python
from forgeboard.core.types import BOMEntry

entry = BOMEntry(
    part_name="Base_Plate",
    part_id="PROJ-MECH-001",
    quantity=2,
    material="Aluminum_6061",
    mass_g=65.0,
    unit_cost=15.0,
    # total_cost auto-computed as unit_cost * quantity = 30.0
    supplier="SendCutSend",
    is_cots=False,
    manufacturing_method="CNC milling",
)
```

### Placement

Rigid-body transform: translation + axis-angle rotation.

```python
from forgeboard.core.types import Placement

p = Placement(
    position=Vector3(x=10, y=20, z=0),
    rotation_axis=AXIS_Z,
    rotation_angle_deg=45.0,
)
p_identity = Placement.identity()
```

### ValidationResult

Outcome of a single validation check.

```python
from forgeboard.core.types import ValidationResult, Severity

result = ValidationResult(
    passed=False,
    severity=Severity.ERROR,
    message="Interference detected between bracket and plate",
    check_name="collision_check",
    details={"volume_mm3": 42.5},
)
```

`Severity` enum: `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

---

## Registry

**Module:** `forgeboard.core.registry`

### ComponentRegistry

Thread-safe component database.

```python
from forgeboard.core.registry import ComponentRegistry

reg = ComponentRegistry()
warnings = reg.load("registry.yaml")     # -> list[ValidationResult]
spec = reg.get("PROJ-MECH-001")          # -> ComponentSpec | None
all_specs = reg.list_all()               # -> list[ComponentSpec] (sorted by id)
structure = reg.list_by_category("structure")  # -> list[ComponentSpec]
categories = reg.categories()            # -> list[str]
results = reg.search("bracket")          # -> list[ComponentSpec]

# Mutation
warnings = reg.add(spec)                 # -> list[ValidationResult]
removed = reg.remove("PROJ-MECH-001")    # -> bool

# Persistence
reg.save("output.yaml")

# Introspection
len(reg)                                 # -> int
"PROJ-MECH-001" in reg                   # -> bool
reg.load_warnings                        # -> list[ValidationResult]
```

---

## Assembly

**Module:** `forgeboard.assembly.orchestrator`

### Assembly

Mutable assembly builder.

```python
from forgeboard.assembly.orchestrator import Assembly

asm = Assembly("MyAssembly")

asm.add_part(
    "base", shape,
    at_origin=True,
    interfaces={"top": ipt},
)

asm.add_part(
    "lid", shape,
    interfaces={"bottom": ipt},
    constraints=[Mate("top", "bottom")],
)

asm.add_constraint("base", "bracket", Align("bore", "shaft"))

solved = asm.solve(engine, collision_tolerance_mm3=1.0, clearance_min_mm=0.2)
```

### SolvedAssembly

Frozen result of solving.

```python
solved.name                  # -> str
solved.parts                 # -> dict[str, SolvedPart]
solved.collisions            # -> list[Collision]
solved.clearance_violations  # -> list[ClearanceViolation]
solved.validation_report     # -> ValidationReport | None
solved.part_count            # -> int
solved.has_collisions        # -> bool
solved.is_valid              # -> bool
```

### Static Methods on Assembly

```python
Assembly.validate(solved, pipeline, engine)       # -> ValidationReport
Assembly.export(solved, engine, "out.step", fmt="step")
Assembly.get_bounding_box(solved, engine)          # -> BoundingBox
Assembly.get_center_of_gravity(solved, engine)     # -> Vector3
Assembly.get_total_mass(solved, engine)             # -> float
```

### Constraint Types

**Module:** `forgeboard.assembly.constraints`

```python
from forgeboard.assembly.constraints import Mate, Flush, Align, Offset, Angle

Mate("interface_a", "interface_b")
Flush("interface_a", "interface_b")
Align("interface_a", "interface_b")
Offset("interface_a", "interface_b", distance_mm=2.5)
Angle("interface_a", "interface_b", angle_deg=45.0)
Angle("interface_a", "interface_b", angle_deg=90.0, hinge_axis=AXIS_X)
```

Each constraint has a `solve()` method:

```python
placement = constraint.solve(part_a_placement, part_a_interface, part_b_interface)
# -> Placement
```

### Collision Detection

**Module:** `forgeboard.assembly.collision`

```python
from forgeboard.assembly.collision import (
    check_pairwise_collisions,
    check_clearance,
    Collision,
    ClearanceViolation,
    CollisionSeverity,
)

collisions = check_pairwise_collisions(
    {"a": shape_a, "b": shape_b}, engine, tolerance_mm3=1.0
)
# -> list[Collision]

violations = check_clearance(
    {"a": shape_a, "b": shape_b}, engine, min_gap_mm=0.2
)
# -> list[ClearanceViolation]
```

`CollisionSeverity` enum: `MINOR` (< 10 mm^3), `MAJOR` (< 100 mm^3),
`CRITICAL` (>= 100 mm^3).

---

## Validation

**Module:** `forgeboard.core.validation`

### ValidationPipeline

```python
from forgeboard.core.validation import (
    ValidationPipeline,
    DimensionCheck,
    MassCheck,
    InterfaceCheck,
)

pipe = ValidationPipeline("my-pipeline")
pipe.add_check(DimensionCheck(required_dimensions=["length_mm", "width_mm"]))
pipe.add_check(MassCheck(mass_budget_g=500))
pipe.add_check(InterfaceCheck(required_interfaces=["top_face"]))

report = pipe.run({"spec": my_spec})
```

### ValidationReport

```python
report.passed               # -> bool
report.error_count           # -> int
report.warning_count         # -> int
report.errors                # -> list[ValidationResult]
report.warnings              # -> list[ValidationResult]
report.criticals             # -> list[ValidationResult]
report.infos                 # -> list[ValidationResult]
report.stopped_early         # -> bool
report.summary()             # -> str
report.to_json("report.json")  # -> str (also writes to file if path given)
```

### Built-in Checks

| Check | Context Keys | Description |
|-------|-------------|-------------|
| `DimensionCheck` | `spec`, `required_dimensions` | Verifies dimensions are present and positive |
| `MassCheck` | `spec`, `mass_budget_g` | Verifies mass is within budget |
| `InterfaceCheck` | `spec`, `required_interfaces` | Verifies interface names exist |

---

## BOM

**Module:** `forgeboard.bom.generator`, `forgeboard.bom.export`

### generate_bom

```python
from forgeboard.bom.generator import generate_bom, BillOfMaterials

bom = generate_bom(solved_assembly, registry)
# -> BillOfMaterials

bom.entries                  # -> list[BOMEntry]
bom.total_mass_g             # -> float
bom.total_cost               # -> float
bom.currency                 # -> str ("USD")
bom.cots_count               # -> int
bom.custom_count             # -> int
bom.fastener_count           # -> int
bom.summary()                # -> str (formatted text table)
```

### Export Functions

```python
from forgeboard.bom.export import export_csv, export_json, export_markdown

export_csv(bom, "output/bom.csv")         # -> Path
export_json(bom, "output/bom.json")       # -> Path
export_markdown(bom, "output/bom.md")     # -> Path
```

---

## CAD Engine

**Module:** `forgeboard.engines.base`, `forgeboard.engines.build123d_engine`

### CadEngine Protocol

See [Extending ForgeBoard](extending.md) for the full method table.

### Build123dEngine

```python
from forgeboard.engines.build123d_engine import Build123dEngine

engine = Build123dEngine()

box = engine.create_box(10, 20, 30)         # -> Shape
cyl = engine.create_cylinder(5, 40)         # -> Shape
scripted = engine.create_from_script("...")  # -> Shape

fused = engine.boolean_union(box, cyl)      # -> Shape
cut = engine.boolean_subtract(box, cyl)     # -> Shape
common = engine.boolean_intersect(box, cyl) # -> Shape

bb = engine.measure_bounding_box(box)       # -> BoundingBox
vol = engine.measure_volume(box)            # -> float (mm^3)
com = engine.measure_center_of_mass(box)    # -> (x, y, z)

result = engine.check_collision(box, cyl)   # -> CollisionResult

moved = engine.move(box, 10, 0, 0)         # -> Shape
rotated = engine.rotate(box, (0, 0, 1), 45) # -> Shape

engine.export_step(fused, "out.step")
engine.export_stl(fused, "out.stl")
engine.render_svg(fused, "iso", "out.svg")
```

### EngineRegistry

```python
from forgeboard.engines.base import EngineRegistry

EngineRegistry.register("my_engine", MyEngineClass)
engine = EngineRegistry.get_engine("build123d")  # -> CadEngine
names = EngineRegistry.available()                # -> list[str]
```

### Shape

Engine-agnostic geometry wrapper.

```python
from forgeboard.engines.base import Shape

s = Shape(
    native=build123d_part,     # engine-specific geometry
    name="Bracket",
    material="Aluminum_6061",
    mass_kg=0.065,
    metadata={"source": "registry"},
)
```

---

## Dependency Graph and Cascade

**Module:** `forgeboard.core.dependency_graph`, `forgeboard.core.cascade`

### DependencyGraph

```python
from forgeboard.core.dependency_graph import DependencyGraph

g = DependencyGraph()
g.add_dependency("pole.od_mm", "clamp.bore_mm", "source + 1.0")
g.add_dependency("clamp.bore_mm", "adapter.id_mm", "source")

affected = g.detect_cascade("pole.od_mm")  # -> ["clamp.bore_mm", "adapter.id_mm"]
order = g.topological_sort()                # -> [...] topological order
g.has_cycle()                               # -> bool
g.dependents("pole.od_mm")                  # -> set[str]
g.dependencies("clamp.bore_mm")             # -> set[str]
```

### CascadeEngine

```python
from forgeboard.core.cascade import CascadeEngine

cascade = CascadeEngine(registry, graph)
result = cascade.apply_change("pole", {"dimensions.outer_diameter": 35.0})

result.source_component       # -> "pole"
result.affected_components    # -> list[AffectedComponent]
result.total_affected         # -> int
result.bom_changed            # -> bool
result.mass_changed           # -> bool

# Preview without applying
preview = cascade.preview_change("pole", {"dimensions.outer_diameter": 35.0})
preview.applied               # -> False

# Auto-detect dependencies from registry interfaces
edges_added = cascade.build_graph_from_registry()
```

---

## CLI

**Entry point:** `forgeboard`

```
forgeboard --version
forgeboard design "M5 bolt flange with 4 holes"
forgeboard assemble --registry assembly.yaml
forgeboard validate --assembly output/assembly.step
forgeboard bom --assembly output/assembly.step --format csv -o bom.csv
forgeboard render --assembly output/assembly.step --views front,right,top,iso
forgeboard serve --host 127.0.0.1 --port 8370
forgeboard sketch --image sketch.png -d "motor bracket" --provider anthropic
```

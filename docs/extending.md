# Extending ForgeBoard

ForgeBoard is designed around Protocol-based abstractions. You can add
new CAD engines, supplier providers, LLM providers, validation checks,
and constraint types without modifying ForgeBoard's core code.

## Adding a New CAD Engine

ForgeBoard's geometry operations are defined by the `CadEngine` protocol
in `forgeboard/engines/base.py`. Any class that implements all the required
methods can be used as a backend.

### Step 1: Implement the Protocol

Create a new file, e.g. `forgeboard/engines/cadquery_engine.py`:

```python
from forgeboard.core.types import BoundingBox
from forgeboard.engines.base import CadEngine, CollisionResult, EngineRegistry, Shape


class CadQueryEngine:
    """CAD engine backed by CadQuery."""

    def __init__(self) -> None:
        import cadquery  # ensure it is installed
        self._cq = cadquery

    def create_box(self, length: float, width: float, height: float) -> Shape:
        result = self._cq.Workplane("XY").box(length, width, height)
        return Shape(native=result, name="Box")

    def create_cylinder(self, radius: float, height: float) -> Shape:
        result = self._cq.Workplane("XY").cylinder(height, radius)
        return Shape(native=result, name="Cylinder")

    def create_from_script(self, script: str) -> Shape:
        namespace = {"cadquery": self._cq, "cq": self._cq}
        exec(script, namespace)
        result = namespace.get("result")
        if result is None:
            raise ValueError("Script must assign to 'result'")
        return Shape(native=result, name="Scripted")

    def boolean_union(self, a: Shape, b: Shape) -> Shape:
        return Shape(native=a.native.union(b.native), name=f"{a.name}+{b.name}")

    def boolean_subtract(self, a: Shape, b: Shape) -> Shape:
        return Shape(native=a.native.cut(b.native), name=f"{a.name}-{b.name}")

    def boolean_intersect(self, a: Shape, b: Shape) -> Shape:
        return Shape(native=a.native.intersect(b.native), name=f"{a.name}&{b.name}")

    def measure_bounding_box(self, shape: Shape) -> BoundingBox:
        bb = shape.native.val().BoundingBox()
        return BoundingBox(
            x_min=bb.xmin, y_min=bb.ymin, z_min=bb.zmin,
            x_max=bb.xmax, y_max=bb.ymax, z_max=bb.zmax,
        )

    def measure_volume(self, shape: Shape) -> float:
        return float(shape.native.val().Volume())

    def measure_center_of_mass(self, shape: Shape) -> tuple[float, float, float]:
        com = shape.native.val().Center()
        return (float(com.x), float(com.y), float(com.z))

    def check_collision(self, a: Shape, b: Shape) -> CollisionResult:
        try:
            intersection = self.boolean_intersect(a, b)
            vol = self.measure_volume(intersection)
        except Exception:
            return CollisionResult(has_collision=False, volume_mm3=0.0)
        return CollisionResult(
            has_collision=vol > 0.01,
            volume_mm3=vol,
        )

    def move(self, shape: Shape, x: float, y: float, z: float) -> Shape:
        moved = shape.native.translate((x, y, z))
        return Shape(native=moved, name=shape.name, material=shape.material,
                     mass_kg=shape.mass_kg, metadata=dict(shape.metadata))

    def rotate(self, shape: Shape, axis: tuple[float, float, float],
               angle_deg: float) -> Shape:
        rotated = shape.native.rotate((0, 0, 0), axis, angle_deg)
        return Shape(native=rotated, name=shape.name, material=shape.material,
                     mass_kg=shape.mass_kg, metadata=dict(shape.metadata))

    def export_step(self, shape: Shape, path: str) -> None:
        self._cq.exporters.export(shape.native, path, "STEP")

    def export_stl(self, shape: Shape, path: str) -> None:
        self._cq.exporters.export(shape.native, path, "STL")

    def render_svg(self, shape: Shape, view: str, path: str) -> None:
        svg_str = self._cq.exporters.export(shape.native, exportType="SVG")
        with open(path, "w") as f:
            f.write(svg_str)
```

### Step 2: Register the Engine

At the bottom of your engine file, register it so ForgeBoard can
discover it:

```python
EngineRegistry.register("cadquery", CadQueryEngine)
```

### Step 3: Use It

```python
from forgeboard.engines.base import EngineRegistry

engine = EngineRegistry.get_engine("cadquery")
box = engine.create_box(10, 20, 30)
```

Or set the `FORGEBOARD_ENGINE` environment variable:

```bash
FORGEBOARD_ENGINE=cadquery forgeboard assemble --registry my.yaml
```

### Required Methods

The full `CadEngine` protocol requires these methods:

| Method | Signature | Purpose |
|--------|-----------|---------|
| `create_box` | `(length, width, height) -> Shape` | Axis-aligned box centered at origin |
| `create_cylinder` | `(radius, height) -> Shape` | Cylinder along Z, base at z=0 |
| `create_from_script` | `(script: str) -> Shape` | Execute backend-specific script |
| `boolean_union` | `(a, b) -> Shape` | Fuse two shapes |
| `boolean_subtract` | `(a, b) -> Shape` | Cut b from a |
| `boolean_intersect` | `(a, b) -> Shape` | Intersection of a and b |
| `measure_bounding_box` | `(shape) -> BoundingBox` | Axis-aligned bounding box |
| `measure_volume` | `(shape) -> float` | Volume in mm^3 |
| `measure_center_of_mass` | `(shape) -> (x, y, z)` | Center of mass in mm |
| `check_collision` | `(a, b) -> CollisionResult` | Intersection detection |
| `move` | `(shape, x, y, z) -> Shape` | Translate |
| `rotate` | `(shape, axis, angle_deg) -> Shape` | Rotate around axis |
| `export_step` | `(shape, path) -> None` | Write STEP file |
| `export_stl` | `(shape, path) -> None` | Write STL file |
| `render_svg` | `(shape, view, path) -> None` | Render SVG projection |

All lengths are in millimeters, angles in degrees.

## Adding a New Supplier Provider

The procurement pipeline uses the `SupplierProvider` protocol from
`forgeboard/procure/provider.py`.

### Step 1: Implement the Protocol

Create a new file, e.g. `forgeboard/procure/providers/rs_components.py`:

```python
from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
    SupplierProvider,
)


class RSComponentsProvider:
    """Supplier provider for RS Components."""

    @property
    def name(self) -> str:
        return "RS Components"

    @property
    def regions(self) -> list[str]:
        return ["GB", "EU", "GLOBAL"]

    @property
    def categories(self) -> list[str]:
        return ["electronics", "sensors", "connectors"]

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        # Implement API call to RS Components search
        ...

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        # Implement pricing lookup
        ...

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        # Implement stock check
        ...
```

### Step 2: Register the Provider

```python
from forgeboard.procure.registry import ProviderRegistry

registry = ProviderRegistry()
registry.register(RSComponentsProvider())
```

### Required Properties and Methods

| Member | Type | Purpose |
|--------|------|---------|
| `name` | property -> str | Human-readable provider name |
| `regions` | property -> list[str] | ISO country codes served (`"GLOBAL"` for worldwide) |
| `categories` | property -> list[str] | Component categories handled (empty = all) |
| `search` | method | Search for products matching a query |
| `get_price` | method | Get pricing for a specific product |
| `check_availability` | method | Check stock and lead time |

## Adding a New LLM Provider

The `LLMProvider` protocol from `forgeboard/design/llm_provider.py`
abstracts AI capabilities.

### Step 1: Implement the Protocol

```python
from forgeboard.design.llm_provider import LLMProvider


class OpenAIProvider:
    """LLM provider backed by OpenAI's API."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o") -> None:
        import openai
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content

    def analyze_image(self, image_path: str, prompt: str) -> str:
        import base64
        with open(image_path, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.choices[0].message.content

    def structured_output(
        self, prompt: str, schema: dict, system: str = ""
    ) -> dict:
        import json
        schema_instruction = (
            f"Respond with JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        )
        full_system = f"{system}\n\n{schema_instruction}" if system else schema_instruction
        raw = self.generate(prompt, system=full_system)
        return json.loads(raw)
```

### Required Methods

| Method | Signature | Purpose |
|--------|-----------|---------|
| `generate` | `(prompt, system) -> str` | Text generation |
| `analyze_image` | `(image_path, prompt) -> str` | Vision (image analysis) |
| `structured_output` | `(prompt, schema, system) -> dict` | JSON-structured output |

## Adding Custom Validation Checks

The validation framework in `forgeboard/core/validation.py` is extensible.

### Using the Pipeline Framework

```python
from forgeboard.core.validation import ValidationCheck, ValidationPipeline
from forgeboard.core.types import Severity, ValidationResult


class ThermalClearanceCheck(ValidationCheck):
    """Verify thermal clearance between heat-generating components."""

    def __init__(self, min_thermal_gap_mm: float = 5.0) -> None:
        super().__init__(
            name="thermal_clearance",
            description="Verify thermal clearance between hot components",
            severity=Severity.WARNING,
        )
        self._min_gap = min_thermal_gap_mm

    def run(self, context: dict) -> ValidationResult:
        spec = context.get("spec")
        if spec is None:
            return ValidationResult(
                passed=True, severity=Severity.INFO,
                message="No spec to check", check_name=self.name,
            )

        # Your thermal clearance logic here
        thermal_keywords = ["heatsink", "motor", "led", "power"]
        is_thermal = any(
            kw in spec.name.lower() or kw in spec.description.lower()
            for kw in thermal_keywords
        )

        if is_thermal and "thermal_gap_mm" not in spec.dimensions:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message=f"'{spec.id}' is a thermal component but has no thermal_gap_mm",
                check_name=self.name,
            )

        return ValidationResult(
            passed=True, severity=Severity.INFO,
            message=f"'{spec.id}' thermal check passed",
            check_name=self.name,
        )


# Use it
pipeline = ValidationPipeline("my-checks")
pipeline.add_check(ThermalClearanceCheck(min_thermal_gap_mm=3.0))
report = pipeline.run({"spec": my_component_spec})
```

### Using the Assembly Validation Pipeline

For assembly-level checks, use the `ValidationRule` callable pattern:

```python
from forgeboard.assembly.orchestrator import SolvedAssembly, ValidationPipeline
from forgeboard.engines.base import CadEngine
from forgeboard.core.types import ValidationResult, Severity


def check_symmetry(solved: SolvedAssembly, engine: CadEngine) -> list[ValidationResult]:
    """Check that the assembly is roughly symmetric about the Y-Z plane."""
    bbox = Assembly.get_bounding_box(solved, engine)
    center_x = bbox.center.x
    if abs(center_x) > 5.0:  # more than 5mm off-center
        return [ValidationResult(
            passed=False,
            severity=Severity.WARNING,
            message=f"Assembly center of mass is {center_x:.1f}mm off the Y-Z plane",
            check_name="symmetry_check",
        )]
    return [ValidationResult(
        passed=True,
        severity=Severity.INFO,
        message="Assembly is approximately symmetric",
        check_name="symmetry_check",
    )]
```

## Adding New Constraint Types

Constraints are defined in `forgeboard/assembly/constraints.py`. To add
a new type, subclass `Constraint` and implement the `solve` method.

### Example: Tangent Constraint

```python
from forgeboard.assembly.constraints import Constraint
from forgeboard.core.types import InterfacePoint, Placement, Vector3


class Tangent(Constraint):
    """Position part B so its surface is tangent to part A's surface.

    Both interfaces should be spherical or cylindrical. The parts are
    positioned so the distance between interface centers equals the sum
    of their radii.
    """

    def solve(
        self,
        part_a_placement: Placement,
        part_a_interface: InterfacePoint,
        part_b_interface: InterfacePoint,
    ) -> Placement:
        r_a = (part_a_interface.diameter_mm or 0.0) / 2.0
        r_b = (part_b_interface.diameter_mm or 0.0) / 2.0

        # Position B so centers are (r_a + r_b) apart along A's normal
        a_world = part_a_placement.position + part_a_interface.position
        direction = part_a_interface.normal.normalized()
        b_center = a_world + direction * (r_a + r_b)

        return Placement(
            position=b_center - part_b_interface.position,
            rotation_axis=Vector3(x=0, y=0, z=1),
            rotation_angle_deg=0.0,
        )
```

Use it like any other constraint:

```python
asm.add_part("sphere", sphere_shape,
    interfaces=sphere_interfaces,
    constraints=[Tangent("outer_surface", "outer_surface")],
)
```

## Plugin Discovery Pattern

ForgeBoard uses explicit registration rather than automatic plugin
discovery. This keeps the system predictable and debuggable.

The registration pattern is:

1. Implement the protocol (CadEngine, SupplierProvider, LLMProvider)
2. Call the appropriate `register()` method
3. Retrieve by name when needed

```python
# Engines
from forgeboard.engines.base import EngineRegistry
EngineRegistry.register("my_engine", MyEngine)
engine = EngineRegistry.get_engine("my_engine")

# Suppliers
from forgeboard.procure.registry import ProviderRegistry
pr = ProviderRegistry()
pr.register(MySupplier())
results = pr.search("M5 bolt", country_code="US")
```

For auto-registration on import, put the `register()` call at module
level (as build123d_engine.py does). Then importing the module is enough
to make the engine available.

# Getting Started

This guide walks you through installing ForgeBoard and building your first
assembly.

## Prerequisites

- **Python 3.11 or later** (3.12 and 3.13 also supported)
- **pip** (included with Python)
- **build123d** (optional for install, required at runtime for geometry operations)

build123d depends on the OpenCASCADE Technology (OCCT) kernel. On most
systems `pip install build123d` handles everything, but see
[Troubleshooting](#troubleshooting) below if you hit issues.

## Installation

### From PyPI

Minimal install (types, registry, BOM -- no geometry engine):

```bash
pip install forgeboard
```

With all optional features (rendering, procurement, MCP server, LLM,
dev tools):

```bash
pip install "forgeboard[all]"
```

You can also pick individual extras:

```bash
pip install "forgeboard[render]"    # SVG/PNG rendering (pyrender, trimesh)
pip install "forgeboard[procure]"   # COTS procurement pipeline (httpx)
pip install "forgeboard[mcp]"       # MCP server for AI agents
pip install "forgeboard[llm]"       # LLM provider (Anthropic Claude)
pip install "forgeboard[dev]"       # pytest, ruff, mypy
```

### From Source

```bash
git clone https://github.com/forgeboard/forgeboard.git
cd forgeboard
pip install -e ".[dev]"
```

### Verify Installation

```bash
forgeboard --version
# forgeboard, version 0.1.0-dev
```

## First Project: Bracket + Bolt + Plate Assembly

This example creates a simple three-component assembly: an aluminum plate,
a steel L-bracket mounted on top, and an M5 bolt holding them together.

### Step 1: Create the Registry File

Save the following as `my_assembly.yaml`:

```yaml
version: "1.0"
project: "Bracket Assembly"

components:
  structure:
    - id: "BRKT-001"
      name: "Base_Plate"
      description: "Flat aluminum plate"
      is_cots: false
      material:
        name: "Aluminum_6061"
        density_g_cm3: 2.70
        cost_per_kg: 8.0
        manufacturing_methods:
          - "CNC milling"
      dimensions:
        length_mm: 80
        width_mm: 60
        thickness_mm: 5
        hole_diameter_mm: 5.5
      interfaces:
        top_face:
          type: "planar"
          position: { x: 0, y: 0, z: 5 }
          normal: { x: 0, y: 0, z: 1 }
        bolt_hole:
          type: "cylindrical"
          position: { x: 20, y: 0, z: 5 }
          normal: { x: 0, y: 0, z: 1 }
          diameter_mm: 5.5
      mass_g: 65
      procurement:
        type: "custom_manufactured"
        unit_cost: 15.00

    - id: "BRKT-002"
      name: "L_Bracket"
      description: "90-degree L-bracket, 3mm steel"
      is_cots: false
      material:
        name: "Steel_1018"
        density_g_cm3: 7.87
        cost_per_kg: 3.0
        manufacturing_methods:
          - "sheet metal bending"
      dimensions:
        leg_length_mm: 40
        leg_width_mm: 40
        thickness_mm: 3
        hole_diameter_mm: 5.5
      interfaces:
        bottom_face:
          type: "planar"
          position: { x: 0, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: -1 }
        bolt_hole:
          type: "cylindrical"
          position: { x: 20, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: -1 }
          diameter_mm: 5.5
      mass_g: 38
      procurement:
        type: "custom_manufactured"
        unit_cost: 8.00

  fasteners:
    - id: "BRKT-003"
      name: "M5x12_Socket_Head"
      description: "M5x12mm socket head cap screw, grade 12.9"
      is_cots: true
      material:
        name: "Alloy_Steel"
        density_g_cm3: 7.85
      dimensions:
        thread_diameter_mm: 5
        length_mm: 12
        head_diameter_mm: 8.5
        head_height_mm: 5
      interfaces:
        shaft:
          type: "cylindrical"
          position: { x: 0, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: -1 }
          diameter_mm: 5
      mass_g: 4.5
      is_fastener: true
      procurement:
        supplier: "McMaster-Carr"
        sku: "91292A128"
        unit_cost: 0.15
        lead_time_days: 2
        url: "https://www.mcmaster.com/91292A128"
```

### Step 2: Build with the CLI

```bash
forgeboard assemble --registry my_assembly.yaml
```

This will:
1. Parse the registry
2. Load all component specs
3. Solve constraints (once implemented, positions parts automatically)
4. Run collision detection
5. Export the assembled STEP file

### Step 3: Generate a BOM

```bash
forgeboard bom --assembly output/assembly.step --format csv
forgeboard bom --assembly output/assembly.step --format json -o bom.json
```

### Step 4: Validate

```bash
forgeboard validate --assembly output/assembly.step
```

### Step 5: Render Views

```bash
forgeboard render --assembly output/assembly.step --views front,right,top,iso
```

### Python API Approach

The same workflow in Python:

```python
from pathlib import Path
from forgeboard.core.registry import ComponentRegistry
from forgeboard.assembly.orchestrator import Assembly
from forgeboard.assembly.constraints import Mate, Align
from forgeboard.engines.build123d_engine import Build123dEngine
from forgeboard.bom.generator import generate_bom

# 1. Load the registry
registry = ComponentRegistry()
warnings = registry.load(Path("my_assembly.yaml"))
for w in warnings:
    print(f"  [{w.severity.value}] {w.message}")

# 2. Create geometry with the engine
engine = Build123dEngine()
plate_shape = engine.create_box(80, 60, 5)
bracket_shape = engine.create_box(40, 40, 3)
bolt_shape = engine.create_cylinder(2.5, 12)

# 3. Build the assembly
plate_spec = registry.get("BRKT-001")
bracket_spec = registry.get("BRKT-002")

asm = Assembly("BracketAssembly")
asm.add_part(
    "base_plate",
    plate_shape,
    at_origin=True,
    interfaces=plate_spec.interfaces,
)
asm.add_part(
    "l_bracket",
    bracket_shape,
    interfaces=bracket_spec.interfaces,
    constraints=[Mate("top_face", "bottom_face")],
)

# 4. Solve
solved = asm.solve(engine)

print(f"Parts: {solved.part_count}")
print(f"Collisions: {len(solved.collisions)}")
print(f"Valid: {solved.is_valid}")

# 5. Export
Assembly.export(solved, engine, "output/assembly.step", fmt="step")

# 6. Generate BOM
bom = generate_bom(solved, registry)
print(bom.summary())
```

### Expected Output

After a successful run you will have:

| File | Description |
|------|-------------|
| `output/assembly.step` | STEP file of the assembled model |
| `bom.csv` or `bom.json` | Bill of materials |
| `renders/*.svg` | Orthographic view renderings |

The BOM will list all three components with mass, cost, supplier data, and
a total.

## Troubleshooting

### build123d fails to install

build123d requires the OCCT kernel. Installation varies by platform:

**Windows:**
```bash
pip install build123d
```
Usually works out of the box on Python 3.11+. If it fails, try:
```bash
pip install --upgrade pip setuptools wheel
pip install build123d
```

**macOS (Apple Silicon):**
```bash
pip install build123d
```
If you get architecture errors:
```bash
arch -x86_64 pip install build123d
```
Or use conda:
```bash
conda install -c conda-forge build123d
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install libgl1-mesa-glx libglu1-mesa
pip install build123d
```

### "No CAD engine registered" error

This means build123d is not installed or failed to import. ForgeBoard's
registry, BOM, and validation features work without it, but assembly
solving and export require a geometry engine:

```bash
pip install build123d
```

### ANTHROPIC_API_KEY not set

The `forgeboard sketch` command and LLM-powered features require an
Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or use the mock provider for testing:

```bash
forgeboard sketch -d "motor bracket" --provider mock
```

### Import errors for optional features

Each optional feature has its own dependency group. Install only what you
need:

```bash
pip install "forgeboard[render]"   # for SVG rendering
pip install "forgeboard[procure]"  # for COTS search
pip install "forgeboard[llm]"      # for AI features
```

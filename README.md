# ForgeBoard

**AI-driven CAD assembly engine. Design parts, validate assemblies, generate BOMs.**

ForgeBoard is an assembly orchestration engine, not a single-part generator. It
coordinates the design of multiple components, constrains them into assemblies,
detects collisions, generates bills of materials, and exports production-ready
STEP/STL files -- all driven by natural language or Python API.

## Quick Start

### Install

```bash
pip install forgeboard
```

With all optional features:

```bash
pip install "forgeboard[all]"
```

### CLI Usage

```bash
# Design components from a text description
forgeboard design "M5 bolt flange with 4 mounting holes on 40mm PCD"

# Assemble components from a registry file
forgeboard assemble --registry assembly.yaml

# Validate an assembly (collision detection, constraint satisfaction)
forgeboard validate --assembly output/assembly.step

# Generate a bill of materials
forgeboard bom --assembly output/assembly.step --format csv

# Render orthographic views
forgeboard render --assembly output/assembly.step --views front,right,top,iso

# Start the MCP server for AI agent integration
forgeboard serve
```

### Python API

```python
from forgeboard import ForgeBoard

fb = ForgeBoard()

# Design a component
bracket = fb.design("L-bracket, 3mm aluminum, 40x40mm, 4x M5 holes")

# Load existing components and assemble
assembly = fb.assemble(
    registry="assembly.yaml",
    validate=True,
)

# Export
assembly.export_step("output/assembly.step")
assembly.export_bom("output/bom.csv")
```

## Features

- **Build123d Engine** -- powered by the Build123d CAD kernel for precise
  solid modeling with full OCCT support
- **Swappable CAD Backend** -- the `CadEngine` Protocol defines the
  interface for geometry operations. Build123d is the default; other
  backends (e.g., FreeCAD) can be plugged in by implementing the protocol
- **Constraint-Based Assembly** -- define mate pairs, axis alignments, and
  offsets; the solver positions components automatically
- **Dry-Fit Bounding-Box Validation** -- the assembly solver auto-generates
  Build123d box proxies from component dimensions when no detailed CAD
  geometry exists yet. This lets you validate layout, clearances, and
  spatial fit early in the design process without modeling every part
- **Collision Detection** -- interference checks between all component pairs
  before export. Pass `skip_collisions=True` to the solver for fast layout
  validation that skips the expensive pairwise collision pass
- **BOM Generation** -- structured bills of materials in CSV, JSON, or
  YAML with mass, material, and sourcing data. Cost calculation accepts
  both `unit_cost` and `unit_cost_usd` keys in the procurement dict
- **MCP Server** -- Model Context Protocol server for integration with
  AI coding agents (Claude Code, etc.)
- **STEP/STL Export** -- production-ready output in industry-standard formats
- **Procurement Pipeline** -- optional COTS component lookup and sourcing
  integration

## Architecture

```
forgeboard/
|-- core/          # Part, Assembly, Constraint data models
|-- engines/       # Build123d geometry generation engine
|-- assembly/      # Constraint solver and assembly orchestration
|-- export/        # STEP, STL, and render export pipelines
|-- bom/           # Bill of materials generation
|-- procure/       # COTS component search and procurement
|-- mcp_server/    # Model Context Protocol server
|-- cli/           # Click-based command-line interface
```

```
                +------------------+
                |   CLI / MCP API  |
                +--------+---------+
                         |
              +----------v-----------+
              |   Assembly Solver    |
              |  (constraints, fit)  |
              +----+-----+-----+----+
                   |     |     |
          +--------+  +--+--+  +--------+
          |           |     |           |
    +-----v---+ +----v----+ +-----v-----+
    | Engine  | | Validate| |  Export    |
    | build123d| | collide | | STEP/STL  |
    +---------+ +---------+ +-----------+
```

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/forgeboard/forgeboard.git
cd forgeboard
pip install -e ".[dev]"

# Run tests
pytest

# Lint and type-check
ruff check .
mypy forgeboard/
```

## License

ForgeBoard is licensed under [FSL-1.1-ALv2](LICENSE.md) (Functional Source
License 1.1, Apache License 2.0 Change License). The source code is available
for non-competing use immediately, and converts to Apache-2.0 after two years.

See [LICENSE.md](LICENSE.md) for full terms.

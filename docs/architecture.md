# Architecture

This document describes ForgeBoard's internal architecture, data flow,
core concepts, and design principles. It is written for developers,
contributors, and AI agents that need to understand how the system works.

## System Diagram

```
                    +--------------------------+
                    |   Entry Points           |
                    |   CLI  |  Python API     |
                    |   MCP Server (planned)   |
                    +----------+---------------+
                               |
                    +----------v---------------+
                    |   ComponentRegistry       |
                    |   (YAML load/save/query)  |
                    +----------+---------------+
                               |
              +----------------+----------------+
              |                |                 |
    +---------v------+  +-----v--------+  +-----v---------+
    |  DependencyGraph|  |  Assembly     |  |  Design       |
    |  CascadeEngine  |  |  Builder      |  |  Analyzer     |
    |  (reactive      |  |  (constraints,|  |  Wizard        |
    |   propagation)  |  |   solver)     |  |  (LLM-powered) |
    +--------+-------+  +-----+--------+  +---------------+
             |                 |
             |        +--------v--------+
             |        |  CadEngine       |
             |        |  (build123d)     |
             |        +--------+--------+
             |                 |
    +--------v---------+  +---v-----------+
    |  Validation       |  |  Export        |
    |  Pipeline         |  |  STEP/STL/SVG |
    |  (collision,      |  +---+-----------+
    |   clearance,      |      |
    |   custom checks)  |  +---v-----------+
    +------------------+  |  BOM Generator  |
                          |  (CSV/JSON/MD)  |
                          +-----------------+
```

## Data Flow

The typical data flow through ForgeBoard follows this pipeline:

```
Input (YAML registry / text description / sketch image)
  |
  v
[1] Registry Load -- parse YAML, validate specs, build ComponentSpec objects
  |
  v
[2] Dependency Graph -- track parameter relationships between components
  |
  v
[3] Assembly Build -- add parts, define constraints (Mate, Flush, Align, ...)
  |
  v
[4] Constraint Solve -- compute placements for all parts in insertion order
  |
  v
[5] Collision Detection -- AABB pre-filter, then exact boolean intersection
  |
  v
[6] Validation -- run pipeline of checks (dimensions, mass, interfaces, custom)
  |
  v
[7] Export -- STEP file, STL mesh, SVG renders, BOM (CSV/JSON/Markdown)
```

Steps 2-3 can also be driven by the cascade engine: when a parameter
changes, affected downstream components are automatically re-evaluated.

## Core Concepts

### Component

The atomic unit ForgeBoard works with. A component is either:

- **Custom** -- manufactured for the project (3D printed, CNC milled, etc.)
- **COTS** (Commercial Off-The-Shelf) -- purchased from a supplier

Each component is described by a `ComponentSpec` (Pydantic model) that
includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier (e.g. `"LAMP-MECH-001"`) |
| `name` | `str` | Human-readable name |
| `description` | `str` | What the component does |
| `category` | `str` | Grouping (structure, electronics, fasteners, ...) |
| `material` | `Material` | Physical material properties |
| `dimensions` | `dict` | Key-value dimension pairs (all in mm) |
| `interfaces` | `dict[str, InterfacePoint]` | Named connection points |
| `mass_g` | `float` | Mass in grams |
| `is_cots` | `bool` | True if purchased, not manufactured |
| `procurement` | `dict` | Supplier, cost, lead time, URL, SKU |
| `metadata` | `dict` | Arbitrary extra data |

### Assembly

A collection of components positioned relative to each other via
constraints. Assemblies can contain other assemblies -- the hierarchy is
flat and recursive. There is no distinction between "sub-assembly" and
"master assembly"; it is assemblies all the way up.

The `Assembly` class is a mutable builder. You add parts and constraints,
then call `solve()` to produce a frozen `SolvedAssembly` with all
placements computed.

### InterfacePoint

A named connection point on a component where it physically mates with
another part. Examples: a bolt hole, a bore fit, a flat mounting face, a
pin slot.

Each interface point has:

| Field | Description |
|-------|-------------|
| `name` | Human-readable label (e.g. `"arm_socket"`) |
| `position` | Location in part-local coordinates (mm) |
| `normal` | Outward-facing direction vector |
| `type` | Surface type: `planar`, `cylindrical`, or `spherical` |
| `diameter_mm` | For cylindrical/spherical interfaces |
| `metadata` | Free-form notes (bolt patterns, tolerances, etc.) |

### Constraint

A geometric relationship between two InterfacePoints on different parts.
Constraints drive the assembly solver -- they define where parts go
relative to each other.

| Type | Behavior |
|------|----------|
| `Mate` | Face-to-face contact. Normals oppose, positions coincide. |
| `Flush` | Coplanar surfaces. Normals align (same direction). |
| `Align` | Coaxial alignment. Cylinder axes become collinear. |
| `Offset` | Mate + fixed distance along the normal direction. |
| `Angle` | Angular relationship between two interface normals. |

### Registry

The YAML-based component database. A registry file contains all component
specs organized by category. The `ComponentRegistry` class loads, queries,
and persists these specs. It is thread-safe for use in server contexts.

### Dependency Graph

Tracks which parameters depend on which other parameters. When the pole
outer diameter changes, the dependency graph knows that the bracket bore
must follow.

The `DependencyGraph` supports:
- BFS cascade detection (find all affected downstream parameters)
- Topological sort (determine safe evaluation order)
- Cycle detection
- Optional formula strings for automatic value propagation

### CascadeEngine

The reactive change propagation engine. When a component parameter changes:

1. Finds all affected downstream components via the dependency graph
2. Topologically sorts them for safe evaluation order
3. Evaluates formulas to compute new values
4. Updates component specs in the registry
5. Notifies listeners of each change

The cascade engine is pure computation -- deterministic, no LLM calls, no
network I/O.

### CadEngine

A pluggable geometry backend. ForgeBoard defines a `CadEngine` Protocol
that any CAD kernel can implement. The default implementation wraps
build123d (which uses OpenCASCADE).

The protocol requires:
- Primitive creation (`create_box`, `create_cylinder`, `create_from_script`)
- Boolean operations (`union`, `subtract`, `intersect`)
- Measurement (`bounding_box`, `volume`, `center_of_mass`)
- Collision detection (`check_collision`)
- Transforms (`move`, `rotate`)
- Export (`export_step`, `export_stl`, `render_svg`)

Engines are registered at runtime via `EngineRegistry.register()` and
retrieved by name via `EngineRegistry.get_engine()`.

### LLMProvider

A pluggable AI backend for features that require human-like judgment:
sketch analysis, the interactive design wizard, and COTS component
research. ForgeBoard defines an `LLMProvider` Protocol with three methods:

| Method | Purpose |
|--------|---------|
| `generate(prompt, system)` | Text generation |
| `analyze_image(image_path, prompt)` | Vision analysis |
| `structured_output(prompt, schema, system)` | JSON-structured output |

Implementations: `AnthropicProvider` (Claude API), `MockProvider` (testing).

## Module Map

| Module | Purpose | Key Dependencies |
|--------|---------|-----------------|
| `core/types.py` | Pydantic data models (Vector3, ComponentSpec, BOMEntry, ...) | pydantic |
| `core/registry.py` | YAML-based component database, load/save/query | pyyaml, core/types |
| `core/dependency_graph.py` | Parameter dependency tracking, topological sort | (none) |
| `core/cascade.py` | Reactive change propagation engine | core/registry, core/dependency_graph |
| `core/validation.py` | Validation pipeline framework, built-in checks | core/types |
| `assembly/constraints.py` | Constraint types (Mate, Flush, Align, Offset, Angle) | core/types |
| `assembly/collision.py` | Collision detection and clearance checking | core/types, engines/base |
| `assembly/orchestrator.py` | Assembly builder, solver, export | assembly/*, engines/base |
| `engines/base.py` | CadEngine protocol, Shape wrapper, EngineRegistry | core/types |
| `engines/build123d_engine.py` | build123d implementation of CadEngine | engines/base, build123d |
| `bom/generator.py` | BOM generation from solved assemblies | assembly/orchestrator, core/registry |
| `bom/export.py` | BOM export to CSV, JSON, Markdown | bom/generator |
| `export/step_export.py` | STEP file export | engines/base |
| `export/stl_export.py` | STL file export | engines/base |
| `export/render.py` | SVG rendering | engines/base |
| `design/analyzer.py` | Sketch/text analysis using LLM | design/llm_provider |
| `design/wizard.py` | Interactive design wizard | design/llm_provider |
| `design/llm_provider.py` | LLMProvider protocol, Anthropic + Mock | anthropic (optional) |
| `procure/provider.py` | SupplierProvider protocol, data types | (none) |
| `procure/registry.py` | Provider registry for supplier backends | procure/provider |
| `procure/providers/` | Concrete supplier implementations | procure/provider, httpx |
| `cli/main.py` | Click-based CLI | click, all modules |
| `mcp_server/` | MCP server (planned for v0.2) | mcp |

## Design Principles

### 1. Deterministic Logic in Python, LLM Only Where AI Judgment Is Needed

All constraint solving, collision detection, BOM generation, cascade
propagation, and validation are pure Python computation. The LLM is used
only for:
- Analyzing sketch images to extract design intent
- Running the interactive wizard to fill in missing details
- COTS component research

This means assembly results are reproducible and testable without any AI
dependency.

### 2. Components + Assemblies (Flat Hierarchy)

There is no "sub-assembly" vs "master assembly" distinction. An assembly
is just a collection of things (components or other assemblies) with
constraints. This recursive, uniform model avoids artificial hierarchy
decisions.

### 3. Reactive Cascade on Any Change

When you change a parameter on one component, all dependent components
are automatically updated through the dependency graph. This is similar
to a spreadsheet: change one cell, and all formulas downstream recompute.

### 4. CAD Engine Agnostic (Protocol-Based)

ForgeBoard does not hard-code any CAD kernel. The `CadEngine` protocol
defines what a backend must do. build123d is the default implementation,
but CadQuery, FreeCAD, or any OCCT wrapper can be added by implementing
the same protocol.

### 5. LLM Provider Agnostic

The `LLMProvider` protocol abstracts AI capabilities. The default uses
Anthropic's Claude, but any vision-capable model (OpenAI, Google, local
models) can be plugged in by implementing three methods.

### 6. Location-Aware Procurement (Local First)

The procurement pipeline queries local suppliers before global ones.
Each `SupplierProvider` declares which regions and categories it covers.
The `ProviderRegistry` orders providers by proximity to the user's
location, minimizing shipping cost and lead time.

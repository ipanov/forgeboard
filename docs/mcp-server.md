# MCP Server

ForgeBoard includes a Model Context Protocol (MCP) server that exposes
its capabilities to AI coding agents. This allows tools like Claude Code,
Cursor, and Windsurf to create CAD components, build assemblies, run
validation, and generate BOMs through natural conversation.

## What is MCP?

The Model Context Protocol is an open standard that lets AI assistants
call external tools. Instead of generating code and hoping it runs
correctly, an AI agent can call a `forgeboard_add_component` tool directly
and get back structured results.

For ForgeBoard, this means an AI agent can:
- Create CAD components with dimensions, materials, and interfaces
- Assemble components with geometric constraints (mate, flush, align, offset, angle)
- Run collision detection and clearance validation
- Generate bills of materials in JSON, CSV, or Markdown
- Export STEP/STL files
- Search for off-the-shelf components from suppliers
- Evaluate buy-vs-build decisions
- Analyze sketches and text descriptions to extract design intent

All without writing Python code or managing build123d directly.

## Installation

Install ForgeBoard with the MCP extra:

```bash
pip install "forgeboard[mcp]"
```

Or from source:

```bash
pip install -e ".[mcp]"
```

## Configuration

### Claude Code

Add to your Claude Code MCP configuration (`~/.claude/settings.json` or
project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "forgeboard": {
      "command": "forgeboard",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Cursor

Add to your Cursor MCP configuration (`.cursor/mcp.json` in your project
root):

```json
{
  "mcpServers": {
    "forgeboard": {
      "command": "forgeboard",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Windsurf

Add to your Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "forgeboard": {
      "command": "forgeboard",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Generic stdio MCP

ForgeBoard's MCP server uses stdio transport. Any MCP client that supports
stdio can connect:

```bash
forgeboard serve
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGEBOARD_ENGINE` | `build123d` | CAD engine backend to use |
| `FORGEBOARD_REGISTRY` | (none) | Path to default registry YAML file |
| `ANTHROPIC_API_KEY` | (none) | Required for LLM-powered design analysis |

## Session State

The MCP server is **stateful**: it maintains a `ForgeProject` instance
across tool calls within a session. This is intentional -- the AI builds
up an assembly incrementally over multiple calls.

State includes:
- **Component registry**: all added components persist across calls
- **Dependency graph**: parameter dependencies and cascade formulas
- **Assemblies**: assembly builders with parts and constraints
- **CAD engine**: if build123d is available, used for geometry operations

## Available Tools

### Project Management

#### `forgeboard_create_project`

Create or reset the project. Must be called before any other tool.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Project name |
| `registry_path` | string | No | Path to component registry YAML file |

**Returns:**
```json
{
  "name": "Desk Lamp",
  "component_count": 0,
  "assembly_count": 0,
  "total_mass_g": 0.0,
  "total_cost": 0.0,
  "status": "created"
}
```

#### `forgeboard_get_project_summary`

Get the current project state.

**Returns:**
```json
{
  "name": "Desk Lamp",
  "component_count": 5,
  "assembly_count": 1,
  "total_mass_g": 450.0,
  "total_cost": 82.50,
  "components": ["POLE-001", "BASE-001", "BRKT-001"],
  "assemblies": ["Main Frame"]
}
```

### Component Management

#### `forgeboard_add_component`

Add a component to the project registry.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Component name |
| `id` | string | Yes | Unique component ID |
| `description` | string | No | What this component does |
| `dimensions` | object | No | Key dimensions in mm |
| `material` | string | No | Material name |
| `mass_g` | float | No | Mass in grams |
| `is_cots` | boolean | No | Off-the-shelf part? |
| `interfaces` | object | No | Named connection points |
| `procurement` | object | No | Supplier, cost, URL, etc. |
| `category` | string | No | Grouping category |

**Returns:** The complete component specification as a dict.

#### `forgeboard_update_component`

Update a component and trigger cascade propagation to all dependents.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `component_id` | string | Yes | Component to modify |
| `changes` | object | Yes | Dotted path changes |

**Returns:** Cascade result with all affected downstream components.

#### `forgeboard_remove_component`

Remove a component from the registry.

#### `forgeboard_get_component`

Get a component's full specification.

#### `forgeboard_list_components`

List all components, optionally filtered by category.

### Assembly

#### `forgeboard_create_assembly`

Create a new named assembly.

#### `forgeboard_add_to_assembly`

Add a component instance to an assembly with constraints.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `assembly_name` | string | Yes | Target assembly |
| `component_id` | string | Yes | Component from registry |
| `instance_name` | string | Yes | Unique name in this assembly |
| `at_origin` | boolean | No | Fix at assembly origin |
| `constraints` | list[object] | No | Geometric constraints |

Constraint format:
```json
[
  {"type": "mate", "interface_a": "pole.top", "interface_b": "bracket.base"},
  {"type": "offset", "interface_a": "base.top", "interface_b": "lid.bottom", "offset_mm": 2.0},
  {"type": "angle", "interface_a": "hinge.pivot", "interface_b": "door.pivot", "angle_deg": 90}
]
```

Supported constraint types: `mate`, `flush`, `align`, `offset`, `angle`.

#### `forgeboard_solve_assembly`

Solve constraint positions, run collision detection and clearance checks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `assembly_name` | string | Yes | Name of the assembly to solve |
| `skip_collisions` | boolean | No | If `true`, skip expensive pairwise collision detection. Use for fast dry-fit layout validation where you only need to verify that constraints resolve and parts have positions. Defaults to `false`. |

**Returns:**
```json
{
  "assembly_name": "Main Frame",
  "part_count": 4,
  "placements": {
    "base_1": {"position": {"x": 0, "y": 0, "z": 0}, ...}
  },
  "collisions": [
    {"part_a": "pole", "part_b": "bracket", "volume_mm3": 15.2, "severity": "major"}
  ],
  "collision_count": 1,
  "clearance_violations": [],
  "has_collisions": true,
  "is_valid": false
}
```

#### `forgeboard_validate_assembly`

Full validation pipeline: collisions, clearance, floating parts, mass budget.

**Returns:**
```json
{
  "passed": false,
  "part_count": 4,
  "collisions": [...],
  "clearance_violations": [...],
  "floating_parts": ["sensor_mount"],
  "total_mass_g": 450.0,
  "per_part_mass_g": {"base": 200.0, "pole": 150.0}
}
```

### Procurement

#### `forgeboard_search_cots`

Search for off-the-shelf components from supplier databases.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search text |
| `category` | string | No | Category filter |
| `country` | string | No | ISO country code for ordering |

#### `forgeboard_buy_or_build`

Evaluate whether to purchase or custom-manufacture a component.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `component_id` | string | Yes | Component to evaluate |

**Returns:**
```json
{
  "component_id": "BRKT-001",
  "decision": "BUILD",
  "confidence": 0.85,
  "reasoning": "'Motor Bracket' appears to be a custom structural part..."
}
```

### Export

#### `forgeboard_export_step`

Export assembly as STEP file.

#### `forgeboard_export_stl`

Export assembly as STL file.

#### `forgeboard_render_views`

Render SVG orthographic views (front, right, top, iso).

#### `forgeboard_generate_bom`

Generate bill of materials in JSON, CSV, or Markdown format.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `assembly_name` | string | No | Specific assembly, or all components |
| `format` | string | No | "json", "csv", or "markdown" |

### Design Analysis

#### `forgeboard_analyze_sketch`

Analyze a sketch image to extract components and dimensions.

#### `forgeboard_analyze_text`

Analyze text description to extract components and missing info.

### Dependencies

#### `forgeboard_preview_change`

Preview cascade effects without applying changes.

#### `forgeboard_add_dependency`

Add a parametric dependency between components.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source` | string | Yes | Source parameter path |
| `target` | string | Yes | Target parameter path |
| `formula` | string | No | Expression using "source" variable |

## Example Workflow

Here is how an AI assistant would create a simple 3-component assembly:

```
1. forgeboard_create_project(name="Motor Mount")

2. forgeboard_add_component(
     name="Base Plate",
     id="BASE-001",
     dimensions={"length_mm": 120, "width_mm": 80, "thickness_mm": 3},
     material="Aluminum_6061",
     mass_g=78.0,
     interfaces={"top_face": {"name": "top_face"}}
   )

3. forgeboard_add_component(
     name="L-Bracket",
     id="BRKT-001",
     dimensions={"leg_length_mm": 42, "width_mm": 30, "thickness_mm": 3},
     material="Aluminum_6061",
     mass_g=22.0,
     interfaces={
       "base_face": {"name": "base_face"},
       "motor_face": {"name": "motor_face"}
     }
   )

4. forgeboard_add_component(
     name="NEMA 17 Stepper Motor",
     id="MOTOR-001",
     dimensions={"width_mm": 42.3, "height_mm": 48},
     mass_g=350.0,
     is_cots=True,
     interfaces={"mount_face": {"name": "mount_face"}},
     procurement={"supplier": "StepperOnline", "unit_cost": 12.99}
   )

5. forgeboard_add_dependency(
     source="BRKT-001.dimensions.leg_length_mm",
     target="MOTOR-001.dimensions.width_mm",
     formula="source"
   )

6. forgeboard_create_assembly(name="Motor Mount Assembly")

7. forgeboard_add_to_assembly(
     assembly_name="Motor Mount Assembly",
     component_id="BASE-001",
     instance_name="base",
     at_origin=True
   )

8. forgeboard_add_to_assembly(
     assembly_name="Motor Mount Assembly",
     component_id="BRKT-001",
     instance_name="bracket",
     constraints=[{
       "type": "mate",
       "interface_a": "top_face",
       "interface_b": "base_face"
     }]
   )

9. forgeboard_add_to_assembly(
     assembly_name="Motor Mount Assembly",
     component_id="MOTOR-001",
     instance_name="motor",
     constraints=[{
       "type": "mate",
       "interface_a": "motor_face",
       "interface_b": "mount_face"
     }]
   )

10. forgeboard_validate_assembly(assembly_name="Motor Mount Assembly")

11. forgeboard_generate_bom(format="markdown")

12. forgeboard_export_step(
      assembly_name="Motor Mount Assembly",
      output_path="output/motor_mount.step"
    )
```

## Dry-Fit Workflow

ForgeBoard supports a dry-fit validation workflow that lets you validate
assembly layout before detailed CAD models exist. When a component has
`dimensions` (length, width, height) but no imported STEP geometry, the
assembly solver automatically generates Build123d bounding-box proxies
and uses those for positioning.

**Steps:**

1. Register components with `forgeboard_add_component`, providing at
   minimum `dimensions` with `length`, `width`, and `height` keys.

2. Add components to an assembly with `forgeboard_add_to_assembly` and
   define constraints between interfaces.

3. Solve with `forgeboard_solve_assembly(assembly_name, skip_collisions=true)`
   to get placements quickly without running the pairwise collision pass.

4. Inspect the returned `placements` dict to verify that parts are
   positioned where you expect them.

5. Later, import real STEP files and re-solve with `skip_collisions=false`
   for full collision and clearance validation.

This workflow is useful during early design exploration when you want to
confirm that parts fit within an envelope and constraints are satisfiable
before investing time in detailed geometry.

## Error Handling

All tools return structured error messages when something goes wrong.
Tools never raise exceptions through the MCP protocol -- errors are
always returned as JSON:

```json
{
  "error": "Component 'PROJ-001' not found in registry"
}
```

Common errors:
- No project created (call `forgeboard_create_project` first)
- Component not found in registry
- Assembly not found
- Interface name not found on component
- Collision detected (returned in validation, not as an error)
- build123d not installed (geometry operations unavailable)
- Cycle detected in dependency graph

## Architecture

The MCP server contains **no business logic**. Every tool delegates to
the existing ForgeBoard Python API:

```
AI Assistant  -->  MCP Protocol  -->  MCP Tools  -->  ForgeBoard API
                   (stdio)            (tools.py)      (project.py,
                                                       orchestrator.py,
                                                       cascade.py, etc.)
```

All logic is in the Python library (deterministic, testable). The MCP
server just marshals inputs and outputs.

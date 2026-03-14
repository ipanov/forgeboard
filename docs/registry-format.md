# Registry Format

ForgeBoard uses YAML files as the primary component database format. This
document is the complete reference for the registry schema.

## File Structure

```yaml
version: "1.0"               # Registry format version (required)
project: "My Project Name"   # Human-readable project name (optional)

components:                   # Component definitions grouped by category
  structure:                  # Category name (arbitrary string)
    - id: "PROJ-MECH-001"    # First component in this category
      name: "Base_Plate"
      ...
    - id: "PROJ-MECH-002"    # Second component
      name: "Bracket"
      ...
  electronics:                # Another category
    - id: "PROJ-ELEC-001"
      name: "LED_Module"
      ...
```

The top-level `components` key maps category names to lists of component
definitions. Categories are arbitrary strings -- use whatever grouping
makes sense for your project (e.g. `structure`, `electronics`, `fasteners`,
`sensors`, `payload`).

## Schema Reference

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Registry format version. Currently `"1.0"`. |
| `project` | string | No | Human-readable project name. |
| `components` | map | Yes | Category name to list of component specs. |

### Component Spec Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | -- | Unique identifier. Convention: `PROJECT-CATEGORY-NNN`. |
| `name` | string | Yes | -- | Human-readable name. Use underscores, not spaces. |
| `description` | string | No | `""` | Free-text description of the component's purpose. |
| `is_cots` | boolean | No | `false` | `true` if purchased off-the-shelf, `false` if custom. |
| `material` | object | No | `null` | Material specification (see below). |
| `dimensions` | map | No | `{}` | Key-value dimension pairs. All values in mm unless noted. |
| `interfaces` | map | No | `{}` | Named connection points (see below). |
| `mass_g` | float | No | `null` | Component mass in grams. |
| `procurement` | map | No | `{}` | Sourcing details (see below). |

Any additional fields not listed above are preserved in the `metadata`
dict and passed through to downstream consumers (BOM, validation, etc.).

### Material Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Material name (e.g. `"Aluminum_6061"`, `"PLA"`). |
| `density_g_cm3` | float | Yes | Density in g/cm^3. |
| `yield_strength_mpa` | float | No | Yield strength in MPa. |
| `thermal_conductivity` | float | No | Thermal conductivity in W/(m*K). |
| `cost_per_kg` | float | No | Raw material cost per kg (USD). |
| `manufacturing_methods` | list[string] | No | Applicable methods (e.g. `"CNC milling"`, `"FDM 3D print"`). |

### Interface Object

Each key under `interfaces` is the interface name. The value is an object:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | No | `"planar"` | Surface type: `"planar"`, `"cylindrical"`, or `"spherical"`. |
| `position` | object | No | `{x:0, y:0, z:0}` | Location in part-local coordinates (mm). |
| `normal` | object | No | `{x:0, y:0, z:1}` | Outward-facing direction vector. |
| `diameter_mm` | float | No | `null` | Diameter for cylindrical/spherical interfaces (mm). |

Position and normal are specified as `{x, y, z}` objects:

```yaml
position: { x: 0, y: 0, z: 8 }
normal: { x: 0, y: 0, z: 1 }
```

Any additional fields on an interface (e.g. `note`, `bolt_pattern`) are
stored in the interface's `metadata` dict.

### Procurement Object

| Field | Type | Description |
|-------|------|-------------|
| `supplier` | string | Supplier or marketplace name. |
| `url` | string | Product page URL. |
| `sku` | string | Supplier-specific part number. |
| `unit_cost` | float | Cost per unit (USD). |
| `lead_time_days` | integer | Estimated delivery time in calendar days. |
| `type` | string | `"custom_manufactured"` or `"purchased"`. |
| `method` | string | Manufacturing method (for custom parts). |
| `material` | string | Raw material description (for custom parts). |
| `notes` | string | Free-text procurement notes. |

All procurement fields are optional. Include what you know.

## Full Example

This is the desk lamp assembly from `forgeboard/schemas/registry_example.yaml`:

```yaml
version: "1.0"
project: "Adjustable Desk Lamp"

components:
  structure:
    - id: "LAMP-MECH-001"
      name: "Base_Plate"
      description: "Weighted base plate that prevents the lamp from tipping over"
      is_cots: false
      material:
        name: "PLA"
        density_g_cm3: 1.24
        yield_strength_mpa: 50.0
        cost_per_kg: 25.0
        manufacturing_methods:
          - "FDM 3D print"
      dimensions:
        diameter_mm: 150
        height_mm: 8
        center_bore_mm: 12.5
        weight_pocket_diameter_mm: 120
        weight_pocket_depth_mm: 5
        rubber_pad_count: 4
        rubber_pad_diameter_mm: 15
      interfaces:
        arm_socket:
          type: "cylindrical"
          position: { x: 0, y: 0, z: 8 }
          normal: { x: 0, y: 0, z: 1 }
          diameter_mm: 12.5
          note: "Receives the telescopic arm bottom tube"
        bottom_pads:
          type: "planar"
          position: { x: 0, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: -1 }
          note: "4x adhesive rubber pads on bottom face"
      mass_g: 220
      procurement:
        type: "custom_manufactured"
        method: "FDM 3D print"
        material: "PLA filament"
        unit_cost: 3.50
        lead_time_days: 1
        notes: "Print with 40% infill for weight."

    - id: "LAMP-MECH-002"
      name: "Telescopic_Arm"
      description: "Two-section telescopic arm allowing height adjustment"
      is_cots: true
      material:
        name: "Aluminum_6061"
        density_g_cm3: 2.70
        yield_strength_mpa: 276.0
        thermal_conductivity: 167.0
        cost_per_kg: 8.0
        manufacturing_methods:
          - "extrusion"
          - "tube drawing"
      dimensions:
        lower_section_od_mm: 12
        upper_section_od_mm: 10
        collapsed_length_mm: 200
        extended_length_mm: 350
      interfaces:
        base_insert:
          type: "cylindrical"
          position: { x: 0, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: -1 }
          diameter_mm: 12
        head_mount:
          type: "cylindrical"
          position: { x: 0, y: 0, z: 350 }
          normal: { x: 0, y: 0, z: 1 }
          diameter_mm: 10
      mass_g: 85
      procurement:
        supplier: "Amazon / AliExpress"
        sku: "ALU-TELE-12-10-350"
        unit_cost: 8.50
        lead_time_days: 7

  electronics:
    - id: "LAMP-ELEC-001"
      name: "LED_Module"
      description: "High-CRI LED module with integrated heatsink"
      is_cots: true
      material:
        name: "Aluminum_heatsink"
        density_g_cm3: 2.70
      dimensions:
        board_diameter_mm: 30
        total_height_mm: 16.6
        mounting_hole_pattern_mm: 30
        mounting_hole_size: "M3"
        mounting_hole_count: 4
      interfaces:
        bracket_mount:
          type: "planar"
          position: { x: 0, y: 0, z: 0 }
          normal: { x: 0, y: 0, z: 1 }
      mass_g: 25
      procurement:
        supplier: "Digi-Key"
        sku: "BXRC-30E1000-B-73"
        unit_cost: 6.75
        lead_time_days: 3
```

## ID Conventions

Use a consistent naming convention for component IDs:

```
PROJECT-CATEGORY-NNN
```

Examples:
- `LAMP-MECH-001` -- Lamp project, mechanical category, component 001
- `BRKT-ELEC-003` -- Bracket project, electronics category, component 003
- `DRONE-SENS-012` -- Drone project, sensors category, component 012

Category codes commonly used:
- `MECH` -- mechanical / structural
- `ELEC` -- electronics
- `SENS` -- sensors
- `COMM` -- communications
- `FAST` -- fasteners

## COTS vs Custom Components

### COTS (Purchased)

Set `is_cots: true` and include full procurement details:

```yaml
- id: "PROJ-ELEC-001"
  name: "LED_Module"
  is_cots: true
  procurement:
    supplier: "Digi-Key"
    sku: "BXRC-30E1000-B-73"
    unit_cost: 6.75
    lead_time_days: 3
    url: "https://www.digikey.com/..."
```

COTS components should have accurate dimensions from the datasheet so
that assembly constraints and collision detection work correctly. You
typically do not need `manufacturing_methods` on the material.

### Custom (Manufactured)

Set `is_cots: false` (or omit it, since `false` is the default) and
describe the manufacturing process:

```yaml
- id: "PROJ-MECH-001"
  name: "Base_Plate"
  is_cots: false
  material:
    name: "Aluminum_6061"
    density_g_cm3: 2.70
    manufacturing_methods:
      - "CNC milling"
  procurement:
    type: "custom_manufactured"
    method: "CNC milling"
    supplier: "SendCutSend"
    unit_cost: 15.00
    lead_time_days: 5
```

### Fasteners

Fasteners are a special case of COTS components. Mark them with
`is_fastener: true` in the metadata so the BOM generator classifies
them separately:

```yaml
- id: "PROJ-FAST-001"
  name: "M5x12_Socket_Head"
  is_cots: true
  is_fastener: true
  procurement:
    supplier: "McMaster-Carr"
    sku: "91292A128"
    unit_cost: 0.15
```

## Organizing Large Registries

For projects with many components, you can split the registry into
multiple YAML files and load them sequentially:

```python
registry = ComponentRegistry()
registry.load("structure.yaml")
registry.load("electronics.yaml")
registry.load("fasteners.yaml")
```

Each file must have the `version` and `components` keys. Components are
merged by ID -- if two files define the same ID, the later load wins.

## Validation on Load

When `registry.load()` is called, each component is validated. Common
warnings:

| Warning | Meaning |
|---------|---------|
| `"has no dimensions defined"` | The `dimensions` dict is empty. |
| `"dimension 'X' is non-positive"` | A numeric dimension is <= 0. |
| `"has no mass_g defined"` | The `mass_g` field is missing. |

These are warnings, not errors -- the component is still loaded. Check
the return value of `load()` for the list of `ValidationResult` objects.

## Saving a Registry

The `ComponentRegistry` can write its contents back to YAML:

```python
registry.save("output_registry.yaml")
```

The output follows the same schema that `load()` expects, so round-tripping
is supported: load, modify, save, load again.

# CLAUDE.md

Instructions for Claude Code when working in the ForgeBoard repository.

## Project Overview

ForgeBoard is an AI-driven CAD assembly orchestration engine. It coordinates
multi-component design, constraint-based assembly, collision detection, BOM
generation, and production-ready export -- powered by the Build123d CAD kernel.

## Architecture

```
forgeboard/
|-- core/          Data models: Part, Assembly, Constraint, Material (Pydantic)
|-- engines/       Build123d geometry generation and manipulation
|-- assembly/      Constraint solver, assembly orchestration, collision detection
|-- export/        STEP, STL, render pipelines
|-- bom/           Bill of materials generation (CSV, JSON, YAML)
|-- procure/       COTS component search and procurement integration
|-- mcp_server/    Model Context Protocol server for AI agent integration
|-- cli/           Click-based CLI entry points
```

## CAD Kernel

- **Build123d** is the primary and only CAD kernel. There is NO FreeCAD
  dependency in this project. All geometry operations use Build123d and its
  underlying OCCT bindings.
- Import paths: `from build123d import *` or specific imports from
  `build123d` submodules.
- Build123d uses the Builder pattern and Algebra API. Prefer the Algebra API
  for clarity in generated code.

## Code Style

- **Formatter/Linter**: ruff (configured in pyproject.toml)
- **Type hints**: Required on all public functions and methods. Use `from
  __future__ import annotations` at the top of every module.
- **Data models**: Use Pydantic BaseModel for all serializable data structures
  (parts, assemblies, constraints, BOM entries).
- **Docstrings**: Google style.
- **Line length**: 88 characters (ruff default).

## Testing

- **Framework**: pytest
- **Geometry assertions**: Always use `pytest.approx()` with appropriate
  tolerances for floating-point geometry comparisons. Example:
  ```python
  assert part.volume() == pytest.approx(expected_volume, rel=1e-3)
  assert edge.length == pytest.approx(40.0, abs=0.01)
  ```
- **Test organization**:
  - `tests/unit/` -- fast, isolated tests (no CAD kernel required where possible)
  - `tests/integration/` -- tests that exercise the Build123d engine
- **Markers**: Use `@pytest.mark.integration` for tests requiring the CAD
  kernel. Use `@pytest.mark.slow` for tests taking more than a few seconds.

## Key Conventions

- All CLI commands are defined in `forgeboard/cli/main.py` using Click.
- Entry point: `forgeboard.cli:main` (see pyproject.toml).
- Configuration and registry files use YAML format.
- Assembly registries define components, constraints, and metadata.
- STEP export is the primary output format; STL is secondary for visualization.

## Dependencies

Core: build123d, pyyaml, pydantic, click

Optional groups (install with `pip install "forgeboard[group]"`):
- render: pyrender, trimesh, Pillow, numpy
- procure: httpx, beautifulsoup4, pdfplumber
- mcp: mcp
- llm: anthropic
- dev: pytest, pytest-cov, ruff, mypy

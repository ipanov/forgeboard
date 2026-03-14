# Contributing to ForgeBoard

## Development Setup

```bash
git clone https://github.com/forgeboard/forgeboard.git
cd forgeboard
python -m venv venv
source venv/bin/activate    # Linux/macOS
# or: venv\Scripts\activate  # Windows

pip install -e ".[dev]"
```

This installs ForgeBoard in editable mode with all development
dependencies (pytest, ruff, mypy).

If you need the full feature set for integration testing:

```bash
pip install -e ".[all]"
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=forgeboard

# Run only fast unit tests (skip integration tests that need build123d)
pytest -m "not integration"

# Run a specific test file
pytest tests/unit/test_types.py -v
```

## Code Style

ForgeBoard uses:

- **ruff** for linting and formatting (configured in `pyproject.toml`)
- **mypy** in strict mode for type checking
- **Pydantic v2** models for data validation
- **Type hints** on all function signatures -- no untyped defs

Before submitting:

```bash
# Lint
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format
ruff format .

# Type check
mypy forgeboard/
```

### Style Conventions

- Use `from __future__ import annotations` at the top of every module.
- Use `str | None` syntax (not `Optional[str]`) in function signatures.
- Use `dataclass` for internal mutable state, `Pydantic BaseModel` for
  validated data that crosses boundaries (user input, config, export).
- Docstrings: use NumPy-style for public API, brief one-liners for
  internal helpers.

## Pull Request Process

1. Fork the repository and create a feature branch from `main`.
2. Make your changes. Add tests for new functionality.
3. Run `ruff check .`, `ruff format .`, `mypy forgeboard/`, and `pytest`.
4. Open a pull request against `main`.
5. Describe what you changed and why in the PR description.

Keep PRs focused -- one feature or fix per PR.

## Reporting Bugs

Open an issue on [GitHub Issues](https://github.com/forgeboard/forgeboard/issues)
with:

- ForgeBoard version (`forgeboard --version`)
- Python version (`python --version`)
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Error messages / tracebacks

## Project Structure

```
forgeboard/
  core/         # Data models, registry, validation, dependency graph
  engines/      # CAD engine protocol + build123d implementation
  assembly/     # Constraint types, solver, collision detection
  bom/          # Bill of materials generation and export
  export/       # STEP, STL, SVG export
  design/       # LLM-powered sketch analysis and wizard
  procure/      # COTS procurement pipeline
  cli/          # Click-based command-line interface
  mcp_server/   # MCP server (planned)
tests/
  unit/         # Fast unit tests (no CAD kernel needed)
  integration/  # Integration tests (require build123d)
```

## License

ForgeBoard is licensed under FSL-1.1-ALv2 (Functional Source License 1.1,
Apache License 2.0 Change License). By contributing, you agree that your
contributions will be licensed under the same terms.

See [LICENSE.md](LICENSE.md) for the full license text.

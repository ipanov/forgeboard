"""
Validation pipeline framework for ForgeBoard.

Provides an extensible system for running ordered sequences of validation
checks against component specs, assemblies, or arbitrary contexts.

Architecture:
    ``ValidationCheck`` -- abstract base for individual checks.
    ``ValidationPipeline`` -- ordered sequence of checks; runs all, stops on
        first critical failure.
    ``ValidationReport`` -- aggregates all results with convenience properties
        (passed, summary, filtering by severity).

Built-in concrete checks:
    ``DimensionCheck`` -- verifies required dimensions are present and positive.
    ``MassCheck`` -- verifies mass is within a budget.
    ``InterfaceCheck`` -- verifies all referenced interfaces exist on the spec.

Inspired by the Clear Skies ``assembly_validator.py`` pattern (collision
detection, spatial sanity, severity classification) but generalized into a
reusable pipeline framework.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

from forgeboard.core.types import (
    ComponentSpec,
    Severity,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ValidationCheck(ABC):
    """Abstract base class for a single validation check.

    Subclass this to implement domain-specific checks.  Each check has a
    ``name``, human-readable ``description``, a default ``severity`` for
    failures, and a ``run()`` method that inspects a context dict and
    returns a ``ValidationResult``.

    The *context* dict is an open-ended bag of data.  Convention:

    * ``"spec"`` -- a ``ComponentSpec``
    * ``"specs"`` -- a list of ``ComponentSpec``
    * ``"assembly"`` -- an ``AssemblySpec``
    * ``"mass_budget_g"`` -- float
    * Any other domain-specific keys the check needs.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        severity: Severity = Severity.ERROR,
    ) -> None:
        self.name = name
        self.description = description
        self.severity = severity

    @abstractmethod
    def run(self, context: dict[str, Any]) -> ValidationResult:
        """Execute the check and return a result."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ValidationPipeline:
    """Ordered sequence of ``ValidationCheck`` instances.

    When ``run()`` is called, every check is executed in order.  If a check
    returns a ``CRITICAL`` severity failure, the pipeline short-circuits and
    skips remaining checks.

    Usage::

        pipe = ValidationPipeline("my-pipeline")
        pipe.add_check(DimensionCheck())
        pipe.add_check(MassCheck(mass_budget_g=500))
        report = pipe.run({"spec": some_spec})
        print(report.summary())
    """

    def __init__(self, name: str = "pipeline") -> None:
        self.name = name
        self._checks: list[ValidationCheck] = []

    def add_check(self, check: ValidationCheck) -> ValidationPipeline:
        """Append a check to the pipeline.  Returns self for chaining."""
        self._checks.append(check)
        return self

    # Keep the old ``add()`` name as an alias for backward compat
    def add(self, check: ValidationCheck) -> None:
        """Append a check (alias for ``add_check``)."""
        self.add_check(check)

    def run(self, context: dict[str, Any]) -> ValidationReport:
        """Execute all checks in order, returning a ``ValidationReport``."""
        results: list[ValidationResult] = []
        stopped_early = False

        for check in self._checks:
            result = check.run(context)
            results.append(result)

            # Stop on first critical failure
            if not result.passed and result.severity == Severity.CRITICAL:
                stopped_early = True
                break

        return ValidationReport(
            pipeline_name=self.name,
            results=results,
            stopped_early=stopped_early,
        )

    @property
    def checks(self) -> list[ValidationCheck]:
        """The ordered list of checks in this pipeline."""
        return list(self._checks)

    def __len__(self) -> int:
        return len(self._checks)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class ValidationReport(BaseModel):
    """Aggregated validation results from a pipeline run."""

    pipeline_name: str = Field(default="", description="Name of the pipeline")
    results: list[ValidationResult] = Field(
        default_factory=list,
        description="Ordered list of check results",
    )
    stopped_early: bool = Field(
        default=False,
        description="True if pipeline stopped on a critical failure",
    )

    @property
    def passed(self) -> bool:
        """True if no errors or critical failures were recorded."""
        return all(
            r.passed or r.severity in (Severity.INFO, Severity.WARNING)
            for r in self.results
        )

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def errors(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if not r.passed and r.severity == Severity.ERROR
        ]

    @property
    def criticals(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if not r.passed and r.severity == Severity.CRITICAL
        ]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if not r.passed and r.severity == Severity.WARNING
        ]

    @property
    def infos(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if not r.passed and r.severity == Severity.INFO
        ]

    def summary(self) -> str:
        """Return a human-readable summary string."""
        total = len(self.results)
        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = total - passed_count
        lines = [
            f"Pipeline: {self.pipeline_name}",
            f"Checks run: {total}",
            f"Passed: {passed_count}, Failed: {failed_count}",
            f"  Critical: {len(self.criticals)}",
            f"  Error: {len(self.errors)}",
            f"  Warning: {len(self.warnings)}",
            f"  Info: {len(self.infos)}",
        ]
        if self.stopped_early:
            lines.append("  (stopped early on critical failure)")
        lines.append(f"Result: {'PASSED' if self.passed else 'FAILED'}")
        return "\n".join(lines)

    def to_json(self, path: Optional[str] = None) -> str:
        """Serialize to JSON.  If *path* is given, also writes to file."""
        data = {
            "pipeline": self.pipeline_name,
            "passed": self.passed,
            "stopped_early": self.stopped_early,
            "results": [
                {
                    "check_name": r.check_name,
                    "passed": r.passed,
                    "severity": r.severity.value,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }
        text = json.dumps(data, indent=2)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------


class DimensionCheck(ValidationCheck):
    """Verify that all required dimensions are present and positive.

    Context keys used:
        ``spec`` -- a ``ComponentSpec`` to validate.
        ``required_dimensions`` -- optional list[str] of dimension keys that
            must be present.  If omitted, checks that at least *some*
            dimensions exist.
    """

    def __init__(
        self,
        required_dimensions: Optional[list[str]] = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            name="dimension_check",
            description="Verify required dimensions are present and positive",
            severity=severity,
        )
        self._required = required_dimensions

    def run(self, context: dict[str, Any]) -> ValidationResult:
        spec: Optional[ComponentSpec] = context.get("spec")
        if spec is None:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message="No 'spec' in validation context",
                check_name=self.name,
            )

        required = self._required or context.get("required_dimensions", [])
        problems: list[str] = []

        # Check that required dimensions exist
        for dim_name in required:
            if dim_name not in spec.dimensions:
                problems.append(f"missing '{dim_name}'")

        # Check all numeric dimensions are positive
        for key, value in spec.dimensions.items():
            if isinstance(value, (int, float)) and value <= 0:
                problems.append(f"'{key}' = {value} (must be > 0)")

        # If no required list was given, at least verify dimensions exist
        if not required and not spec.dimensions:
            problems.append("no dimensions defined at all")

        if problems:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message=(
                    f"Dimension issues on '{spec.id}': "
                    + "; ".join(problems)
                ),
                check_name=self.name,
                details={"problems": problems, "component_id": spec.id},
            )

        return ValidationResult(
            passed=True,
            severity=Severity.INFO,
            message=f"All dimensions valid for '{spec.id}'",
            check_name=self.name,
        )


class MassCheck(ValidationCheck):
    """Verify component mass is within a budget.

    Context keys used:
        ``spec`` -- a ``ComponentSpec``
        ``mass_budget_g`` -- float (can also be set at init time)
    """

    def __init__(
        self,
        mass_budget_g: Optional[float] = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            name="mass_check",
            description="Verify mass is within budget",
            severity=severity,
        )
        self._budget = mass_budget_g

    def run(self, context: dict[str, Any]) -> ValidationResult:
        spec: Optional[ComponentSpec] = context.get("spec")
        if spec is None:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message="No 'spec' in validation context",
                check_name=self.name,
            )

        budget = self._budget or context.get("mass_budget_g")
        if budget is None:
            return ValidationResult(
                passed=True,
                severity=Severity.INFO,
                message="No mass budget specified, skipping",
                check_name=self.name,
            )

        if spec.mass_g is None:
            return ValidationResult(
                passed=False,
                severity=Severity.WARNING,
                message=f"Component '{spec.id}' has no mass_g defined",
                check_name=self.name,
                details={"component_id": spec.id, "budget_g": budget},
            )

        if spec.mass_g > budget:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message=(
                    f"Component '{spec.id}' mass {spec.mass_g}g "
                    f"exceeds budget {budget}g"
                ),
                check_name=self.name,
                details={
                    "component_id": spec.id,
                    "mass_g": spec.mass_g,
                    "budget_g": budget,
                    "over_by_g": spec.mass_g - budget,
                },
            )

        return ValidationResult(
            passed=True,
            severity=Severity.INFO,
            message=(
                f"Component '{spec.id}' mass {spec.mass_g}g "
                f"within budget {budget}g"
            ),
            check_name=self.name,
            details={
                "component_id": spec.id,
                "mass_g": spec.mass_g,
                "budget_g": budget,
            },
        )


class InterfaceCheck(ValidationCheck):
    """Verify that all referenced interface names actually exist on the spec.

    Context keys used:
        ``spec`` -- a ``ComponentSpec``
        ``required_interfaces`` -- optional list[str] of interface names
    """

    def __init__(
        self,
        required_interfaces: Optional[list[str]] = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            name="interface_check",
            description="Verify all referenced interfaces exist",
            severity=severity,
        )
        self._required = required_interfaces

    def run(self, context: dict[str, Any]) -> ValidationResult:
        spec: Optional[ComponentSpec] = context.get("spec")
        if spec is None:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message="No 'spec' in validation context",
                check_name=self.name,
            )

        required = self._required or context.get("required_interfaces", [])
        missing = [
            iname for iname in required if iname not in spec.interfaces
        ]

        if missing:
            return ValidationResult(
                passed=False,
                severity=self.severity,
                message=(
                    f"Component '{spec.id}' missing interfaces: "
                    + ", ".join(missing)
                ),
                check_name=self.name,
                details={
                    "component_id": spec.id,
                    "missing": missing,
                    "available": list(spec.interfaces.keys()),
                },
            )

        return ValidationResult(
            passed=True,
            severity=Severity.INFO,
            message=f"All required interfaces present on '{spec.id}'",
            check_name=self.name,
            details={
                "component_id": spec.id,
                "interfaces": list(spec.interfaces.keys()),
            },
        )

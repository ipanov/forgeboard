"""Sketch and text analysis for ForgeBoard design input.

Provides :class:`DesignAnalyzer`, which accepts sketches (images), text
descriptions, or both, and produces structured analysis results that
identify components, dimensions, materials, assembly relationships, and
ambiguities requiring clarification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from forgeboard.design.llm_provider import LLMProvider
from forgeboard.design.prompts import (
    SKETCH_ANALYSIS_PROMPT,
    SKETCH_ANALYSIS_WITH_CONTEXT_PROMPT,
    TEXT_ANALYSIS_PROMPT,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class IdentifiedComponent(BaseModel):
    """A single component identified during sketch or text analysis.

    Attributes
    ----------
    name:
        Human-readable component name (e.g. "L-Bracket", "NEMA 17 Motor").
    shape_description:
        Plain-text description of the geometry.
    estimated_dimensions:
        Key dimensions extracted or estimated, in millimeters.
    interfaces:
        Named connection points or mating surfaces.
    is_cots_candidate:
        Whether this looks like a standard purchasable part.
    confidence:
        How confident the analysis is in this identification (0.0--1.0).
    """

    name: str = Field(description="Descriptive component name")
    shape_description: str = Field(
        default="", description="Plain-text geometry description"
    )
    estimated_dimensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Estimated dimensions in mm (length_mm, width_mm, etc.)",
    )
    interfaces: list[str] = Field(
        default_factory=list,
        description="Connection points or mating surfaces",
    )
    is_cots_candidate: bool = Field(
        default=False,
        description="True if this appears to be a standard purchasable part",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Identification confidence (0.0 to 1.0)",
    )


class AssemblyRelationship(BaseModel):
    """A detected relationship between two components."""

    part_a: str = Field(description="First component name")
    part_b: str = Field(description="Second component name")
    relationship: str = Field(
        default="unknown",
        description="Connection type (bolted, press-fit, welded, glued, hinged, threaded, unknown)",
    )


class SketchAnalysis(BaseModel):
    """Result of analyzing a sketch or image.

    Captures everything the vision model could extract from the image,
    including explicit ambiguities that need human clarification.
    """

    identified_components: list[IdentifiedComponent] = Field(
        default_factory=list,
        description="Components identified in the sketch",
    )
    detected_dimensions: dict[str, float] = Field(
        default_factory=dict,
        description="Labeled dimensions found in the sketch (mm)",
    )
    detected_materials: list[str] = Field(
        default_factory=list,
        description="Material annotations visible in the sketch",
    )
    assembly_relationships: list[AssemblyRelationship] = Field(
        default_factory=list,
        description="Detected connections between components",
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description="Things that are unclear, missing, or ambiguous",
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall analysis confidence (0.0 to 1.0)",
    )


class TextAnalysis(BaseModel):
    """Result of analyzing a pure text description."""

    components: list[IdentifiedComponent] = Field(
        default_factory=list,
        description="Components parsed from the text",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Design constraints mentioned in the text",
    )
    materials: list[str] = Field(
        default_factory=list,
        description="Materials mentioned or implied",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Information not provided but needed for full specification",
    )


class DesignAnalysis(BaseModel):
    """Merged analysis result combining sketch and/or text inputs.

    This is the primary output of :meth:`DesignAnalyzer.analyze_combined`
    and serves as the input to :class:`~forgeboard.design.wizard.DesignWizard`.
    """

    components: list[IdentifiedComponent] = Field(
        default_factory=list,
        description="All identified components",
    )
    dimensions: dict[str, float] = Field(
        default_factory=dict,
        description="All detected or specified dimensions (mm)",
    )
    materials: list[str] = Field(
        default_factory=list,
        description="All mentioned materials",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Design constraints",
    )
    assembly_relationships: list[AssemblyRelationship] = Field(
        default_factory=list,
        description="Connections between components",
    )
    completeness_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How complete the design specification is (0.0 to 1.0)",
    )
    missing_details: list[str] = Field(
        default_factory=list,
        description="Details still needed to fully specify the design",
    )
    source: str = Field(
        default="unknown",
        description="Input source: 'sketch', 'text', or 'combined'",
    )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class DesignAnalyzer:
    """Analyzes sketches and text descriptions to extract structured design intent.

    Parameters
    ----------
    llm_provider:
        An object satisfying :class:`~forgeboard.design.llm_provider.LLMProvider`.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm = llm_provider

    # -- Public API --------------------------------------------------------

    def analyze_sketch(
        self, image_path: str, description: str = ""
    ) -> SketchAnalysis:
        """Analyze a sketch image, optionally with text context.

        Parameters
        ----------
        image_path:
            Path to the image file (PNG, JPEG, etc.).
        description:
            Optional text description to provide additional context.

        Returns
        -------
        SketchAnalysis
            Structured extraction of components, dimensions, materials,
            relationships, and ambiguities.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {image_path}")

        if description:
            prompt = SKETCH_ANALYSIS_WITH_CONTEXT_PROMPT.format(
                description=description
            )
        else:
            prompt = SKETCH_ANALYSIS_PROMPT

        raw = self.llm.analyze_image(image_path, prompt)
        data = _parse_json_response(raw)

        return _build_sketch_analysis(data)

    def analyze_text(self, description: str) -> TextAnalysis:
        """Analyze a pure text description.

        Parameters
        ----------
        description:
            Natural-language description of the desired part or assembly.

        Returns
        -------
        TextAnalysis
            Structured extraction of components, constraints, materials,
            and missing information.
        """
        if not description.strip():
            return TextAnalysis(missing_info=["No description provided"])

        schema = {
            "type": "object",
            "properties": {
                "components": {"type": "array"},
                "constraints": {"type": "array"},
                "materials": {"type": "array"},
                "missing_info": {"type": "array"},
            },
        }

        data = self.llm.structured_output(
            prompt=description,
            schema=schema,
            system=TEXT_ANALYSIS_PROMPT,
        )

        return _build_text_analysis(data)

    def analyze_combined(
        self, image_path: str | None, description: str
    ) -> DesignAnalysis:
        """Combined analysis from sketch and/or text.

        At least one of *image_path* or *description* must be non-empty.

        Parameters
        ----------
        image_path:
            Path to a sketch image, or ``None`` for text-only analysis.
        description:
            Text description (may be empty if image_path is provided).

        Returns
        -------
        DesignAnalysis
            Merged result with a completeness score and list of missing
            details.
        """
        sketch_result: SketchAnalysis | None = None
        text_result: TextAnalysis | None = None

        if image_path is not None:
            sketch_result = self.analyze_sketch(image_path, description=description)

        if description.strip():
            text_result = self.analyze_text(description)

        if sketch_result is None and text_result is None:
            return DesignAnalysis(
                completeness_score=0.0,
                missing_details=["No input provided (no sketch and no text)"],
                source="unknown",
            )

        return _merge_analyses(sketch_result, text_result)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Attempt to parse a JSON response, handling markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n")
        cleaned = cleaned[first_nl + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {"components": [], "ambiguities": ["Failed to parse LLM response"]}


def _build_sketch_analysis(data: dict[str, Any]) -> SketchAnalysis:
    """Build a SketchAnalysis from parsed LLM JSON."""
    components: list[IdentifiedComponent] = []
    for comp_data in data.get("components", []):
        components.append(
            IdentifiedComponent(
                name=comp_data.get("name", "Unknown"),
                shape_description=comp_data.get("shape_description", ""),
                estimated_dimensions=comp_data.get("estimated_dimensions", {}),
                interfaces=comp_data.get("interfaces", []),
                is_cots_candidate=comp_data.get("is_cots_candidate", False),
                confidence=comp_data.get("confidence", 0.5),
            )
        )

    relationships: list[AssemblyRelationship] = []
    for rel_data in data.get("assembly_relationships", []):
        relationships.append(
            AssemblyRelationship(
                part_a=rel_data.get("part_a", ""),
                part_b=rel_data.get("part_b", ""),
                relationship=rel_data.get("relationship", "unknown"),
            )
        )

    return SketchAnalysis(
        identified_components=components,
        detected_dimensions=data.get("detected_dimensions", {}),
        detected_materials=data.get("detected_materials", []),
        assembly_relationships=relationships,
        ambiguities=data.get("ambiguities", []),
        confidence_score=data.get("confidence_score", 0.0),
    )


def _build_text_analysis(data: dict[str, Any]) -> TextAnalysis:
    """Build a TextAnalysis from parsed LLM JSON."""
    components: list[IdentifiedComponent] = []
    for comp_data in data.get("components", []):
        if isinstance(comp_data, dict):
            components.append(
                IdentifiedComponent(
                    name=comp_data.get("name", "Unknown"),
                    shape_description=comp_data.get("shape_description", ""),
                    estimated_dimensions=comp_data.get("estimated_dimensions", {}),
                    interfaces=comp_data.get("interfaces", []),
                    is_cots_candidate=comp_data.get("is_cots_candidate", False),
                    confidence=comp_data.get("confidence", 0.5),
                )
            )

    return TextAnalysis(
        components=components,
        constraints=data.get("constraints", []),
        materials=data.get("materials", []),
        missing_info=data.get("missing_info", []),
    )


def _merge_analyses(
    sketch: SketchAnalysis | None,
    text: TextAnalysis | None,
) -> DesignAnalysis:
    """Merge sketch and text analyses into a unified DesignAnalysis."""
    components: list[IdentifiedComponent] = []
    dimensions: dict[str, float] = {}
    materials: list[str] = []
    constraints: list[str] = []
    relationships: list[AssemblyRelationship] = []
    missing: list[str] = []
    source = "unknown"

    if sketch is not None and text is not None:
        source = "combined"
        # Merge components: use sketch components as base, add any from text
        # that are not already present (by name).
        seen_names: set[str] = set()
        for comp in sketch.identified_components:
            components.append(comp)
            seen_names.add(comp.name.lower())
        for comp in text.components:
            if comp.name.lower() not in seen_names:
                components.append(comp)
                seen_names.add(comp.name.lower())

        dimensions.update(sketch.detected_dimensions)
        materials.extend(sketch.detected_materials)
        materials.extend(
            m for m in text.materials if m not in sketch.detected_materials
        )
        constraints.extend(text.constraints)
        relationships.extend(sketch.assembly_relationships)

        # Missing = text.missing_info + sketch.ambiguities, deduplicated.
        seen_missing: set[str] = set()
        for item in sketch.ambiguities + text.missing_info:
            lower = item.lower()
            if lower not in seen_missing:
                missing.append(item)
                seen_missing.add(lower)

    elif sketch is not None:
        source = "sketch"
        components.extend(sketch.identified_components)
        dimensions.update(sketch.detected_dimensions)
        materials.extend(sketch.detected_materials)
        relationships.extend(sketch.assembly_relationships)
        missing.extend(sketch.ambiguities)

    elif text is not None:
        source = "text"
        components.extend(text.components)
        materials.extend(text.materials)
        constraints.extend(text.constraints)
        missing.extend(text.missing_info)

    # Compute completeness score.
    completeness = _compute_completeness(components, dimensions, materials, missing)

    return DesignAnalysis(
        components=components,
        dimensions=dimensions,
        materials=materials,
        constraints=constraints,
        assembly_relationships=relationships,
        completeness_score=completeness,
        missing_details=missing,
        source=source,
    )


def _compute_completeness(
    components: list[IdentifiedComponent],
    dimensions: dict[str, float],
    materials: list[str],
    missing: list[str],
) -> float:
    """Heuristic completeness score (0.0 to 1.0).

    Scoring criteria:
    - At least one component identified: +0.2
    - Components have dimensions: +0.2
    - Materials specified: +0.1
    - Components have high confidence: +0.2
    - Penalty for each missing detail: -0.05 (min 0.0)
    """
    if not components:
        return 0.0

    score = 0.0

    # Components identified.
    score += 0.2

    # Dimensions coverage: fraction of components with at least one dimension.
    comps_with_dims = sum(
        1
        for c in components
        if any(v is not None and v != 0 for v in c.estimated_dimensions.values())
    )
    if components:
        score += 0.2 * (comps_with_dims / len(components))

    # Global dimensions found.
    if dimensions:
        score += 0.1

    # Materials.
    if materials:
        score += 0.1

    # Average confidence of identified components.
    avg_conf = sum(c.confidence for c in components) / len(components)
    score += 0.2 * avg_conf

    # Penalty for missing details.
    penalty = len(missing) * 0.05
    score = max(0.0, score - penalty)

    return min(1.0, round(score, 2))

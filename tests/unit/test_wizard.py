"""Unit tests for the ForgeBoard design input module.

Tests cover:
- Sketch analysis returns IdentifiedComponents via MockProvider
- Text analysis extracts components from a description
- Wizard generates questions for missing dimensions
- Wizard marks session complete when all details are filled
- Wizard prioritizes critical questions first
- Finalize produces valid ComponentSpecs
- Combined analysis merges sketch + text results
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forgeboard.core.types import ComponentSpec
from forgeboard.design.analyzer import (
    DesignAnalysis,
    DesignAnalyzer,
    IdentifiedComponent,
    SketchAnalysis,
    TextAnalysis,
)
from forgeboard.design.llm_provider import MockProvider
from forgeboard.design.wizard import (
    DesignWizard,
    QuestionType,
    WizardQuestion,
    WizardSession,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sketch_response() -> str:
    """Mock LLM response for sketch analysis."""
    return json.dumps(
        {
            "components": [
                {
                    "name": "L-Bracket",
                    "shape_description": "L-shaped aluminum plate with mounting holes",
                    "estimated_dimensions": {
                        "length_mm": 42,
                        "width_mm": 42,
                        "height_mm": 3,
                    },
                    "interfaces": ["motor_mount_face", "extrusion_slot"],
                    "is_cots_candidate": False,
                    "confidence": 0.8,
                },
                {
                    "name": "NEMA 17 Motor",
                    "shape_description": "Standard NEMA 17 stepper motor",
                    "estimated_dimensions": {
                        "length_mm": 42,
                        "width_mm": 42,
                        "height_mm": 40,
                    },
                    "interfaces": ["mounting_face", "shaft"],
                    "is_cots_candidate": True,
                    "confidence": 0.95,
                },
            ],
            "detected_dimensions": {"bracket_thickness": 3.0},
            "detected_materials": ["aluminum"],
            "assembly_relationships": [
                {
                    "part_a": "L-Bracket",
                    "part_b": "NEMA 17 Motor",
                    "relationship": "bolted",
                }
            ],
            "ambiguities": [
                "Bracket arm lengths not annotated",
                "Bolt size not specified",
            ],
            "confidence_score": 0.7,
        }
    )


def _text_response() -> dict[str, Any]:
    """Mock structured response for text analysis."""
    return {
        "components": [
            {
                "name": "Mounting Bracket",
                "shape_description": "L-shaped bracket for motor mounting",
                "estimated_dimensions": {
                    "length_mm": 50,
                    "width_mm": 42,
                    "height_mm": 3,
                },
                "interfaces": ["motor_face", "frame_face"],
                "is_cots_candidate": False,
                "confidence": 0.75,
            }
        ],
        "constraints": ["3mm thick aluminum", "must fit 20x20 extrusion"],
        "materials": ["aluminum"],
        "missing_info": [
            "Exact arm lengths not specified",
            "Aluminum alloy not specified",
            "Bolt size for extrusion not specified",
        ],
    }


def _wizard_question_response() -> dict[str, Any]:
    """Mock structured response for wizard question generation."""
    return {
        "id": "dim_bracket_arm_length",
        "text": "What should the arm lengths of the L-bracket be?",
        "question_type": "dimension",
        "options": ["30mm x 30mm", "40mm x 40mm", "50mm x 50mm", "Custom (specify)"],
        "context": "Arm lengths determine the bracket's structural capacity and fit.",
        "priority": 1,
        "target_component": "L-Bracket",
    }


def _wizard_complete_response() -> dict[str, Any]:
    """Mock response when all questions are resolved."""
    return {
        "id": "COMPLETE",
        "text": "",
        "question_type": "general",
        "options": [],
        "context": "",
        "priority": 99,
        "target_component": None,
    }


def _component_gen_response() -> list[dict[str, Any]]:
    """Mock structured response for component generation."""
    return [
        {
            "name": "L-Bracket",
            "id": "STRUCT-001",
            "description": "L-shaped mounting bracket for NEMA 17 motor",
            "category": "structure",
            "material": {
                "name": "Aluminum_6061",
                "density_g_cm3": 2.7,
                "yield_strength_mpa": 276.0,
                "cost_per_kg": 8.0,
                "manufacturing_methods": ["CNC milling"],
            },
            "dimensions": {
                "length_mm": 50,
                "width_mm": 42,
                "height_mm": 3,
            },
            "interfaces": {
                "motor_mount": {
                    "name": "motor_mount",
                    "type": "planar",
                },
                "extrusion_slot": {
                    "name": "extrusion_slot",
                    "type": "planar",
                },
            },
            "mass_g": 17.0,
            "is_cots": False,
            "procurement": {},
            "metadata": {"manufacturing_method": "cnc"},
        },
        {
            "name": "NEMA 17 Motor",
            "id": "ACT-001",
            "description": "Standard NEMA 17 stepper motor",
            "category": "actuator",
            "material": None,
            "dimensions": {
                "length_mm": 42,
                "width_mm": 42,
                "height_mm": 40,
            },
            "interfaces": {},
            "mass_g": 350.0,
            "is_cots": True,
            "procurement": {
                "supplier": "StepperOnline",
                "unit_cost": 12.50,
            },
            "metadata": {},
        },
    ]


@pytest.fixture
def mock_provider() -> MockProvider:
    """MockProvider configured with responses for the full workflow."""
    return MockProvider(
        responses={
            "sketch": _sketch_response(),
            "analyze": _sketch_response(),
        },
        structured_responses={
            # Text analysis uses structured_output with the user description
            # in the prompt.  The key must NOT match unrelated prompts such as
            # the component-generation prompt (which may contain "bracket" in
            # the serialized analysis JSON).  Use a phrase that only appears
            # when the user's description is the prompt text.
            "mount a motor": _text_response(),
            "aluminum bracket": _text_response(),
            # Wizard question generation -- matches the wizard question template.
            "most important question": _wizard_question_response(),
            # Component generation -- matches the component generation template.
            "ComponentSpec": _component_gen_response(),
        },
    )


@pytest.fixture
def sketch_image(tmp_path: Path) -> str:
    """Create a dummy image file for testing."""
    img_path = tmp_path / "sketch.png"
    # Write a minimal valid PNG (1x1 white pixel).
    import struct
    import zlib

    def _minimal_png() -> bytes:
        signature = b"\x89PNG\r\n\x1a\n"
        # IHDR
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        # IDAT
        raw_data = zlib.compress(b"\x00\xff\xff\xff")
        idat_crc = zlib.crc32(b"IDAT" + raw_data) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw_data)) + b"IDAT" + raw_data + struct.pack(">I", idat_crc)
        # IEND
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return signature + ihdr + idat + iend

    img_path.write_bytes(_minimal_png())
    return str(img_path)


@pytest.fixture
def sample_analysis() -> DesignAnalysis:
    """A pre-built DesignAnalysis with gaps to fill."""
    return DesignAnalysis(
        components=[
            IdentifiedComponent(
                name="L-Bracket",
                shape_description="L-shaped plate with holes",
                estimated_dimensions={"length_mm": 42, "width_mm": 42},
                interfaces=["motor_mount_face", "extrusion_slot"],
                is_cots_candidate=False,
                confidence=0.8,
            ),
            IdentifiedComponent(
                name="NEMA 17 Motor",
                shape_description="Standard stepper motor",
                estimated_dimensions={
                    "length_mm": 42,
                    "width_mm": 42,
                    "height_mm": 40,
                },
                interfaces=["mounting_face"],
                is_cots_candidate=True,
                confidence=0.95,
            ),
        ],
        dimensions={"bracket_thickness": 3.0},
        materials=["aluminum"],
        constraints=["3mm thick"],
        completeness_score=0.45,
        missing_details=[
            "Bracket arm lengths not specified",
            "Aluminum alloy not specified",
            "Bolt size for attachment not specified",
            "Manufacturing method not specified",
        ],
        source="combined",
    )


# ---------------------------------------------------------------------------
# Sketch analysis tests
# ---------------------------------------------------------------------------


class TestSketchAnalysis:
    """Tests for DesignAnalyzer.analyze_sketch()."""

    def test_returns_identified_components(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_sketch(sketch_image)

        assert isinstance(result, SketchAnalysis)
        assert len(result.identified_components) == 2
        assert result.identified_components[0].name == "L-Bracket"
        assert result.identified_components[1].name == "NEMA 17 Motor"

    def test_components_have_dimensions(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_sketch(sketch_image)

        bracket = result.identified_components[0]
        assert bracket.estimated_dimensions.get("length_mm") == 42
        assert bracket.estimated_dimensions.get("width_mm") == 42

    def test_cots_candidate_flag(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_sketch(sketch_image)

        bracket = result.identified_components[0]
        motor = result.identified_components[1]
        assert bracket.is_cots_candidate is False
        assert motor.is_cots_candidate is True

    def test_detects_ambiguities(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_sketch(sketch_image)

        assert len(result.ambiguities) >= 1
        assert any("arm length" in a.lower() for a in result.ambiguities)

    def test_detects_assembly_relationships(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_sketch(sketch_image)

        assert len(result.assembly_relationships) == 1
        rel = result.assembly_relationships[0]
        assert rel.part_a == "L-Bracket"
        assert rel.relationship == "bolted"

    def test_file_not_found_raises(self, mock_provider: MockProvider) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        with pytest.raises(FileNotFoundError):
            analyzer.analyze_sketch("/nonexistent/path/sketch.png")


# ---------------------------------------------------------------------------
# Text analysis tests
# ---------------------------------------------------------------------------


class TestTextAnalysis:
    """Tests for DesignAnalyzer.analyze_text()."""

    def test_extracts_components(self, mock_provider: MockProvider) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_text(
            "I need an L-shaped bracket to mount a motor"
        )

        assert isinstance(result, TextAnalysis)
        # The MockProvider returns structured_responses when "bracket" is in prompt.
        assert len(result.components) >= 1

    def test_identifies_missing_info(self, mock_provider: MockProvider) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_text(
            "I need an L-shaped bracket to mount a motor"
        )

        assert len(result.missing_info) >= 1

    def test_empty_description_returns_missing(
        self, mock_provider: MockProvider
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_text("")

        assert len(result.missing_info) >= 1
        assert any("no description" in m.lower() for m in result.missing_info)

    def test_materials_extracted(self, mock_provider: MockProvider) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_text(
            "3mm thick aluminum bracket for NEMA 17 motor"
        )

        assert "aluminum" in result.materials


# ---------------------------------------------------------------------------
# Combined analysis tests
# ---------------------------------------------------------------------------


class TestCombinedAnalysis:
    """Tests for DesignAnalyzer.analyze_combined()."""

    def test_merges_sketch_and_text(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_combined(
            sketch_image, "aluminum bracket for a stepper motor"
        )

        assert isinstance(result, DesignAnalysis)
        assert result.source == "combined"
        assert len(result.components) >= 1

    def test_text_only_when_no_image(self, mock_provider: MockProvider) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_combined(
            None, "aluminum bracket for NEMA 17"
        )

        assert result.source == "text"
        assert len(result.components) >= 1

    def test_completeness_score_in_range(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_combined(
            sketch_image, "aluminum bracket"
        )

        assert 0.0 <= result.completeness_score <= 1.0

    def test_missing_details_populated(
        self, mock_provider: MockProvider, sketch_image: str
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_combined(sketch_image, "bracket")

        # There should be at least some ambiguities from the sketch.
        assert len(result.missing_details) >= 1

    def test_no_input_returns_zero_completeness(
        self, mock_provider: MockProvider
    ) -> None:
        analyzer = DesignAnalyzer(mock_provider)
        result = analyzer.analyze_combined(None, "")

        assert result.completeness_score == 0.0
        assert len(result.missing_details) >= 1


# ---------------------------------------------------------------------------
# Wizard question generation tests
# ---------------------------------------------------------------------------


class TestWizardQuestions:
    """Tests for DesignWizard.next_question()."""

    def test_generates_question_for_missing_dimensions(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        question = wizard.next_question(session)
        assert question is not None
        assert isinstance(question, WizardQuestion)
        assert question.text != ""

    def test_question_has_id(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        question = wizard.next_question(session)
        assert question is not None
        assert question.id != ""

    def test_question_has_valid_type(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        question = wizard.next_question(session)
        assert question is not None
        assert isinstance(question.question_type, QuestionType)

    def test_question_prefers_multiple_choice(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        question = wizard.next_question(session)
        assert question is not None
        # The mock returns options for the dimension question.
        assert len(question.options) >= 2

    def test_prioritizes_critical_questions(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        question = wizard.next_question(session)
        assert question is not None
        # Dimension questions should have priority 1 (highest).
        assert question.priority <= 3


# ---------------------------------------------------------------------------
# Wizard session completion tests
# ---------------------------------------------------------------------------


class TestWizardCompletion:
    """Tests for wizard session lifecycle."""

    def test_session_starts_incomplete(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        assert session.is_complete is False
        assert session.completeness < 1.0

    def test_answering_increases_completeness(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)
        initial = session.completeness

        question = wizard.next_question(session)
        assert question is not None

        session = wizard.answer(session, question.id, "40mm x 40mm")
        assert session.completeness >= initial

    def test_marks_complete_when_all_details_filled(
        self, mock_provider: MockProvider,
    ) -> None:
        """A session with no missing details should be immediately complete."""
        complete_analysis = DesignAnalysis(
            components=[
                IdentifiedComponent(
                    name="Widget",
                    estimated_dimensions={"length_mm": 10},
                    confidence=0.9,
                )
            ],
            materials=["PLA"],
            completeness_score=0.95,
            missing_details=[],
            source="text",
        )

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(complete_analysis)

        assert session.is_complete is True

    def test_returns_none_when_complete(
        self, mock_provider: MockProvider,
    ) -> None:
        complete_analysis = DesignAnalysis(
            components=[
                IdentifiedComponent(name="Part", confidence=0.9)
            ],
            completeness_score=0.95,
            missing_details=[],
            source="text",
        )

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(complete_analysis)

        question = wizard.next_question(session)
        assert question is None

    def test_max_questions_limit(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)
        session.max_questions = 2

        q1 = wizard.next_question(session)
        assert q1 is not None
        session = wizard.answer(session, q1.id, "answer1")

        q2 = wizard.next_question(session)
        if q2 is not None:
            session = wizard.answer(session, q2.id, "answer2")

        q3 = wizard.next_question(session)
        # After max_questions (2), should return None.
        assert q3 is None


# ---------------------------------------------------------------------------
# Wizard finalize tests
# ---------------------------------------------------------------------------


class TestWizardFinalize:
    """Tests for DesignWizard.finalize()."""

    def test_produces_component_specs(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        # Configure mock to return component specs on finalization.
        mock_provider._structured["ComponentSpec"] = _component_gen_response()

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        assert len(specs) >= 1
        assert all(isinstance(s, ComponentSpec) for s in specs)

    def test_specs_have_valid_ids(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        mock_provider._structured["ComponentSpec"] = _component_gen_response()

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        for spec in specs:
            assert spec.id.strip() != ""

    def test_specs_have_names(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        mock_provider._structured["ComponentSpec"] = _component_gen_response()

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        for spec in specs:
            assert spec.name.strip() != ""

    def test_cots_spec_has_procurement(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        mock_provider._structured["ComponentSpec"] = _component_gen_response()

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        cots_specs = [s for s in specs if s.is_cots]
        assert len(cots_specs) >= 1
        assert cots_specs[0].procurement.get("supplier") is not None

    def test_custom_spec_has_material(
        self, mock_provider: MockProvider, sample_analysis: DesignAnalysis
    ) -> None:
        mock_provider._structured["ComponentSpec"] = _component_gen_response()

        wizard = DesignWizard(mock_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        custom_specs = [s for s in specs if not s.is_cots]
        assert len(custom_specs) >= 1
        assert custom_specs[0].material is not None
        assert custom_specs[0].material.name == "Aluminum_6061"

    def test_fallback_when_llm_returns_empty(
        self, sample_analysis: DesignAnalysis
    ) -> None:
        """When the LLM returns nothing, fallback builds specs from analysis."""
        empty_provider = MockProvider(
            structured_responses={"ComponentSpec": []},
        )
        wizard = DesignWizard(empty_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        # Fallback should produce specs from the analysis components.
        assert len(specs) == 2
        assert specs[0].name == "L-Bracket"
        assert specs[1].name == "NEMA 17 Motor"

    def test_fallback_specs_have_auto_ids(
        self, sample_analysis: DesignAnalysis
    ) -> None:
        empty_provider = MockProvider(
            structured_responses={"ComponentSpec": []},
        )
        wizard = DesignWizard(empty_provider)
        session = wizard.start_session(sample_analysis)

        specs = wizard.finalize(session)
        assert specs[0].id == "AUTO-001"
        assert specs[1].id == "AUTO-002"


# ---------------------------------------------------------------------------
# MockProvider protocol tests
# ---------------------------------------------------------------------------


class TestMockProvider:
    """Tests verifying MockProvider satisfies the LLMProvider protocol."""

    def test_generates_text(self) -> None:
        provider = MockProvider(responses={"hello": "world"})
        result = provider.generate("say hello")
        assert result == "world"

    def test_analyze_image_returns_string(self, sketch_image: str) -> None:
        provider = MockProvider(responses={"sketch": '{"components": []}'})
        result = provider.analyze_image(sketch_image, "analyze this sketch")
        assert isinstance(result, str)

    def test_structured_output_returns_dict(self) -> None:
        provider = MockProvider(
            structured_responses={"test": {"answer": 42}}
        )
        result = provider.structured_output("test prompt", schema={})
        assert result == {"answer": 42}

    def test_call_log_tracks_calls(self) -> None:
        provider = MockProvider()
        provider.generate("prompt1")
        provider.generate("prompt2", system="sys")

        assert len(provider.call_log) == 2
        assert provider.call_log[0]["prompt"] == "prompt1"
        assert provider.call_log[1]["system"] == "sys"

    def test_default_fallback(self) -> None:
        provider = MockProvider()
        result = provider.generate("anything")
        assert isinstance(result, str)

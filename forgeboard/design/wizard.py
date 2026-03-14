"""Interactive design clarification wizard for ForgeBoard.

Provides :class:`DesignWizard`, which takes a :class:`DesignAnalysis`
with gaps and ambiguities and drives a question-answer loop -- one
question at a time, preferring multiple-choice options -- until the
design is fully specified.

The wizard uses an LLM to generate contextually appropriate questions
and to convert the completed session into
:class:`~forgeboard.core.types.ComponentSpec` objects.
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from forgeboard.core.types import ComponentSpec, InterfacePoint, Material
from forgeboard.design.analyzer import DesignAnalysis, IdentifiedComponent
from forgeboard.design.llm_provider import LLMProvider
from forgeboard.design.prompts import (
    COMPONENT_GENERATION_PROMPT,
    WIZARD_QUESTION_PROMPT,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    """Category of a wizard clarification question."""

    DIMENSION = "dimension"
    MATERIAL = "material"
    INTERFACE = "interface"
    MANUFACTURING = "manufacturing"
    COTS_CHECK = "cots_check"
    TOLERANCE = "tolerance"
    GENERAL = "general"


class WizardQuestion(BaseModel):
    """A single clarifying question posed by the wizard.

    If *options* is non-empty, the question is presented as multiple
    choice.  Otherwise it is open-ended free text.
    """

    id: str = Field(description="Unique question identifier")
    text: str = Field(description="The question to display to the user")
    question_type: QuestionType = Field(
        default=QuestionType.GENERAL,
        description="Category of the question",
    )
    options: list[str] = Field(
        default_factory=list,
        description="Multiple-choice options (empty for open-ended)",
    )
    context: str = Field(
        default="",
        description="Brief explanation of why this question matters",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority (1 = highest, 10 = lowest)",
    )
    target_component: str | None = Field(
        default=None,
        description="Name of the component this question concerns",
    )


class WizardSession(BaseModel):
    """Mutable state of an in-progress wizard session.

    The session accumulates questions and answers and tracks overall
    completeness.  It is designed to be passed back and forth between
    :meth:`DesignWizard.next_question` and :meth:`DesignWizard.answer`.
    """

    session_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        description="Unique session identifier",
    )
    analysis: DesignAnalysis = Field(
        description="The original design analysis driving the session"
    )
    questions_asked: list[WizardQuestion] = Field(
        default_factory=list,
        description="Questions that have been presented to the user",
    )
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of question_id to user answer",
    )
    component_specs: list[ComponentSpec] = Field(
        default_factory=list,
        description="ComponentSpecs built up as answers come in",
    )
    completeness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Current design completeness estimate (0.0 to 1.0)",
    )
    is_complete: bool = Field(
        default=False,
        description="True when no more questions are needed",
    )
    max_questions: int = Field(
        default=20,
        description="Safety limit on total questions",
    )


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class DesignWizard:
    """Interactive wizard that asks questions to fill gaps in a design analysis.

    The wizard drives a one-question-at-a-time loop.  It prefers multiple-
    choice options and prioritizes questions by importance (dimensions first,
    then component type, materials, interfaces, manufacturing, tolerances).

    Parameters
    ----------
    llm_provider:
        An object satisfying :class:`~forgeboard.design.llm_provider.LLMProvider`.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm = llm_provider

    # -- Public API --------------------------------------------------------

    def start_session(self, analysis: DesignAnalysis) -> WizardSession:
        """Start a wizard session from an analysis with ambiguities.

        If the analysis is already complete (no missing details), the
        returned session will have ``is_complete=True``.

        Parameters
        ----------
        analysis:
            A :class:`DesignAnalysis` produced by
            :class:`~forgeboard.design.analyzer.DesignAnalyzer`.

        Returns
        -------
        WizardSession
            A new session ready for question iteration.
        """
        session = WizardSession(
            analysis=analysis,
            completeness=analysis.completeness_score,
        )

        if not analysis.missing_details and analysis.completeness_score >= 0.9:
            session.is_complete = True

        return session

    def next_question(self, session: WizardSession) -> WizardQuestion | None:
        """Generate the next clarifying question.

        Returns ``None`` when the session is complete or the maximum
        question count has been reached.

        Parameters
        ----------
        session:
            The current wizard session.

        Returns
        -------
        WizardQuestion or None
            The next question, or None if no more are needed.
        """
        if session.is_complete:
            return None

        if len(session.questions_asked) >= session.max_questions:
            session.is_complete = True
            return None

        # Build context for the LLM.
        remaining_missing = self._remaining_missing(session)
        if not remaining_missing:
            session.is_complete = True
            return None

        # Try LLM-generated question.
        question = self._generate_question_via_llm(session, remaining_missing)
        if question is not None and question.id == "COMPLETE":
            session.is_complete = True
            return None

        # Fallback: generate a rule-based question from the missing items.
        if question is None:
            question = self._generate_fallback_question(session, remaining_missing)

        if question is None:
            session.is_complete = True
            return None

        session.questions_asked.append(question)
        return question

    def answer(
        self, session: WizardSession, question_id: str, answer: str
    ) -> WizardSession:
        """Process the user's answer and update the session state.

        Parameters
        ----------
        session:
            The current wizard session.
        question_id:
            The ``id`` of the question being answered.
        answer:
            The user's response (free text or selected option).

        Returns
        -------
        WizardSession
            The updated session.
        """
        session.answers[question_id] = answer

        # Find the question to determine what it was about.
        matched_question: WizardQuestion | None = None
        for q in session.questions_asked:
            if q.id == question_id:
                matched_question = q
                break

        if matched_question is not None:
            self._apply_answer(session, matched_question, answer)

        # Recalculate completeness.
        remaining = self._remaining_missing(session)
        if not remaining:
            session.completeness = 1.0
            session.is_complete = True
        else:
            # Increase completeness proportionally.
            total_missing = len(session.analysis.missing_details)
            if total_missing > 0:
                resolved = total_missing - len(remaining)
                session.completeness = min(
                    1.0, session.analysis.completeness_score + resolved * 0.1
                )

        return session

    def finalize(self, session: WizardSession) -> list[ComponentSpec]:
        """Convert a completed wizard session into ComponentSpecs.

        Parameters
        ----------
        session:
            A wizard session (ideally with ``is_complete=True``).

        Returns
        -------
        list[ComponentSpec]
            Fully specified component specifications ready for CAD
            generation.
        """
        # Try LLM-based generation.
        specs = self._generate_specs_via_llm(session)
        if specs:
            return specs

        # Fallback: build specs from the analysis components directly.
        return self._build_specs_from_session(session)

    # -- Private helpers ---------------------------------------------------

    def _remaining_missing(self, session: WizardSession) -> list[str]:
        """Items from missing_details not yet addressed by answers."""
        answered_topics: set[str] = set()
        for q in session.questions_asked:
            if q.id in session.answers:
                if q.target_component:
                    answered_topics.add(q.target_component.lower())
                answered_topics.add(q.question_type.value)
                # Add the lower-cased question id as an addressed topic.
                answered_topics.add(q.id.lower())

        remaining: list[str] = []
        for detail in session.analysis.missing_details:
            # Check if any answered topic seems to address this detail.
            detail_lower = detail.lower()
            addressed = False
            for topic in answered_topics:
                if topic in detail_lower or detail_lower in topic:
                    addressed = True
                    break
            if not addressed:
                remaining.append(detail)

        return remaining

    def _generate_question_via_llm(
        self, session: WizardSession, remaining: list[str]
    ) -> WizardQuestion | None:
        """Use the LLM to generate a contextual question."""
        analysis_summary = json.dumps(
            {
                "components": [
                    {"name": c.name, "dimensions": c.estimated_dimensions}
                    for c in session.analysis.components
                ],
                "materials": session.analysis.materials,
                "constraints": session.analysis.constraints,
            },
            indent=2,
        )

        qa_history = json.dumps(
            {
                q.id: {"question": q.text, "answer": session.answers.get(q.id, "")}
                for q in session.questions_asked
                if q.id in session.answers
            },
            indent=2,
        )

        missing_items = json.dumps(remaining, indent=2)

        prompt = WIZARD_QUESTION_PROMPT.format(
            analysis_state=analysis_summary,
            qa_history=qa_history,
            missing_items=missing_items,
        )

        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "text": {"type": "string"},
                "question_type": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
                "priority": {"type": "integer"},
                "target_component": {"type": ["string", "null"]},
            },
        }

        try:
            data = self.llm.structured_output(prompt=prompt, schema=schema)
        except Exception:
            return None

        if not data or not data.get("id") or not data.get("text"):
            return None

        q_type_raw = data.get("question_type", "general")
        try:
            q_type = QuestionType(q_type_raw)
        except ValueError:
            q_type = QuestionType.GENERAL

        priority_raw = data.get("priority", 5)
        priority = max(1, min(10, int(priority_raw)))

        return WizardQuestion(
            id=data["id"],
            text=data["text"],
            question_type=q_type,
            options=data.get("options", []),
            context=data.get("context", ""),
            priority=priority,
            target_component=data.get("target_component"),
        )

    def _generate_fallback_question(
        self, session: WizardSession, remaining: list[str]
    ) -> WizardQuestion | None:
        """Generate a rule-based question from the first missing item."""
        if not remaining:
            return None

        item = remaining[0]
        item_lower = item.lower()

        # Classify the missing item.
        if any(kw in item_lower for kw in ("dimension", "length", "width", "height", "size", "diameter", "thick", "arm")):
            return WizardQuestion(
                id=f"dim_{len(session.questions_asked)}",
                text=f"Please specify: {item}",
                question_type=QuestionType.DIMENSION,
                options=[
                    "20mm",
                    "30mm",
                    "40mm",
                    "50mm",
                    "Custom (specify)",
                ],
                context="Accurate dimensions are required to generate geometry.",
                priority=1,
            )
        elif any(kw in item_lower for kw in ("material", "alloy", "plastic", "metal")):
            return WizardQuestion(
                id=f"mat_{len(session.questions_asked)}",
                text=f"Please clarify the material: {item}",
                question_type=QuestionType.MATERIAL,
                options=[
                    "Aluminum 6061",
                    "Stainless Steel 304",
                    "PLA (3D print)",
                    "ABS (3D print)",
                    "Nylon (PA12)",
                    "Other (please specify)",
                ],
                context="Material affects manufacturing method, cost, and strength.",
                priority=2,
            )
        elif any(kw in item_lower for kw in ("bolt", "mount", "attach", "connect", "interface", "fit")):
            return WizardQuestion(
                id=f"iface_{len(session.questions_asked)}",
                text=f"Please clarify the connection: {item}",
                question_type=QuestionType.INTERFACE,
                options=[
                    "Bolted (M3)",
                    "Bolted (M4)",
                    "Bolted (M5)",
                    "Press-fit",
                    "Glued / adhesive",
                    "Snap-fit",
                    "Other (please specify)",
                ],
                context="Connection type determines interface geometry and fastener selection.",
                priority=3,
            )
        elif any(kw in item_lower for kw in ("manufactur", "cnc", "print", "mold", "fabricat")):
            return WizardQuestion(
                id=f"mfg_{len(session.questions_asked)}",
                text=f"How should this be manufactured? {item}",
                question_type=QuestionType.MANUFACTURING,
                options=[
                    "CNC machining",
                    "FDM 3D printing",
                    "SLA 3D printing",
                    "Sheet metal / laser cut",
                    "Injection molding",
                    "Other (please specify)",
                ],
                context="Manufacturing method constrains geometry and tolerances.",
                priority=4,
            )
        else:
            return WizardQuestion(
                id=f"general_{len(session.questions_asked)}",
                text=f"Please provide more detail: {item}",
                question_type=QuestionType.GENERAL,
                options=[],
                context="This information is needed to complete the design specification.",
                priority=5,
            )

    def _apply_answer(
        self, session: WizardSession, question: WizardQuestion, answer: str
    ) -> None:
        """Update session analysis based on the answer.

        This is best-effort: it patches dimensions, materials, etc.
        into the analysis so downstream processing has the data.
        """
        if question.question_type == QuestionType.MATERIAL:
            if answer not in session.analysis.materials:
                session.analysis.materials.append(answer)

        elif question.question_type == QuestionType.DIMENSION:
            # Try to parse a numeric value from the answer.
            try:
                value = float(answer.replace("mm", "").strip())
                key = question.id.replace("dim_", "answered_dim_")
                session.analysis.dimensions[key] = value
            except ValueError:
                # Store as a constraint instead.
                session.analysis.constraints.append(
                    f"{question.text}: {answer}"
                )

        elif question.question_type == QuestionType.MANUFACTURING:
            session.analysis.constraints.append(
                f"Manufacturing method: {answer}"
            )

        elif question.question_type == QuestionType.INTERFACE:
            session.analysis.constraints.append(
                f"Connection: {answer}"
            )

    def _generate_specs_via_llm(
        self, session: WizardSession
    ) -> list[ComponentSpec]:
        """Use the LLM to produce ComponentSpecs from the session."""
        analysis_json = session.analysis.model_dump_json(indent=2)

        qa_pairs: dict[str, str] = {}
        for q in session.questions_asked:
            if q.id in session.answers:
                qa_pairs[q.text] = session.answers[q.id]
        qa_json = json.dumps(qa_pairs, indent=2)

        prompt = COMPONENT_GENERATION_PROMPT.format(
            analysis=analysis_json,
            qa_pairs=qa_json,
        )

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "material": {"type": ["object", "null"]},
                    "dimensions": {"type": "object"},
                    "interfaces": {"type": "object"},
                    "mass_g": {"type": ["number", "null"]},
                    "is_cots": {"type": "boolean"},
                    "procurement": {"type": "object"},
                    "metadata": {"type": "object"},
                },
            },
        }

        try:
            data = self.llm.structured_output(prompt=prompt, schema=schema)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        specs: list[ComponentSpec] = []
        for item in data:
            try:
                spec = _dict_to_component_spec(item)
                specs.append(spec)
            except Exception:
                continue

        return specs

    def _build_specs_from_session(
        self, session: WizardSession
    ) -> list[ComponentSpec]:
        """Fallback: build ComponentSpecs directly from analysis components."""
        specs: list[ComponentSpec] = []

        for idx, comp in enumerate(session.analysis.components):
            comp_id = f"AUTO-{idx + 1:03d}"
            material: Material | None = None

            # Use the first material from the analysis if available.
            if session.analysis.materials:
                mat_name = session.analysis.materials[0]
                material = _guess_material(mat_name)

            spec = ComponentSpec(
                name=comp.name,
                id=comp_id,
                description=comp.shape_description,
                category="uncategorized",
                material=material,
                dimensions=comp.estimated_dimensions,
                interfaces={
                    iface: InterfacePoint(name=iface) for iface in comp.interfaces
                },
                is_cots=comp.is_cots_candidate,
                metadata={
                    "source": "wizard_fallback",
                    "confidence": comp.confidence,
                },
            )
            specs.append(spec)

        return specs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dict_to_component_spec(data: dict[str, Any]) -> ComponentSpec:
    """Convert a raw dict (from LLM output) to a ComponentSpec."""
    material: Material | None = None
    mat_data = data.get("material")
    if mat_data and isinstance(mat_data, dict) and mat_data.get("name"):
        material = Material(
            name=mat_data["name"],
            density_g_cm3=mat_data.get("density_g_cm3", 1.0),
            yield_strength_mpa=mat_data.get("yield_strength_mpa"),
            cost_per_kg=mat_data.get("cost_per_kg"),
            manufacturing_methods=mat_data.get("manufacturing_methods", []),
        )

    interfaces: dict[str, InterfacePoint] = {}
    iface_data = data.get("interfaces", {})
    if isinstance(iface_data, dict):
        for iname, ispec in iface_data.items():
            if isinstance(ispec, dict):
                interfaces[iname] = InterfacePoint(
                    name=ispec.get("name", iname),
                )

    return ComponentSpec(
        name=data.get("name", "Unnamed"),
        id=data.get("id", f"AUTO-{uuid.uuid4().hex[:6]}"),
        description=data.get("description", ""),
        category=data.get("category", "uncategorized"),
        material=material,
        dimensions=data.get("dimensions", {}),
        interfaces=interfaces,
        mass_g=data.get("mass_g"),
        is_cots=data.get("is_cots", False),
        procurement=data.get("procurement", {}),
        metadata=data.get("metadata", {}),
    )


def _guess_material(name: str) -> Material:
    """Return a Material with approximate properties for common names."""
    lower = name.lower()
    if "aluminum" in lower or "aluminium" in lower or "6061" in lower:
        return Material(
            name="Aluminum_6061",
            density_g_cm3=2.7,
            yield_strength_mpa=276.0,
            cost_per_kg=8.0,
            manufacturing_methods=["CNC milling", "extrusion"],
        )
    elif "steel" in lower or "stainless" in lower:
        return Material(
            name="Stainless_Steel_304",
            density_g_cm3=8.0,
            yield_strength_mpa=215.0,
            cost_per_kg=12.0,
            manufacturing_methods=["CNC milling", "sheet metal"],
        )
    elif "pla" in lower:
        return Material(
            name="PLA",
            density_g_cm3=1.24,
            cost_per_kg=25.0,
            manufacturing_methods=["FDM 3D print"],
        )
    elif "abs" in lower:
        return Material(
            name="ABS",
            density_g_cm3=1.05,
            cost_per_kg=30.0,
            manufacturing_methods=["FDM 3D print", "injection molding"],
        )
    elif "nylon" in lower or "pa12" in lower:
        return Material(
            name="Nylon_PA12",
            density_g_cm3=1.01,
            cost_per_kg=50.0,
            manufacturing_methods=["SLS 3D print", "injection molding"],
        )
    else:
        return Material(
            name=name,
            density_g_cm3=1.0,
        )

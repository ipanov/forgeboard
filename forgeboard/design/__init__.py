"""Design input module for ForgeBoard.

Provides three input modes for creating CAD component specifications:

1. **Text description** -- plain-text requirements parsed into structured
   component specs via LLM analysis.
2. **Sketch / image analysis** -- hand-drawn sketches, whiteboard photos, or
   technical drawings analyzed through a vision-capable LLM to extract
   geometry, dimensions, materials, and assembly relationships.
3. **Interactive wizard** -- a guided question-answer loop that identifies
   gaps in the analysis and asks targeted clarifying questions (one at a
   time, preferring multiple choice) until the design intent is complete.

The module is LLM-provider-agnostic.  All AI calls go through the
:class:`~forgeboard.design.llm_provider.LLMProvider` protocol, with
concrete implementations for Anthropic (Claude) and a mock for testing.

Typical workflow::

    from forgeboard.design import DesignAnalyzer, DesignWizard, MockProvider

    llm = MockProvider()
    analyzer = DesignAnalyzer(llm)
    analysis = analyzer.analyze_combined("sketch.png", "RC car chassis")

    wizard = DesignWizard(llm)
    session = wizard.start_session(analysis)
    while not session.is_complete:
        q = wizard.next_question(session)
        if q is None:
            break
        session = wizard.answer(session, q.id, user_input())
    specs = wizard.finalize(session)
"""

from __future__ import annotations

from forgeboard.design.llm_provider import (
    AnthropicProvider,
    LLMProvider,
    MockProvider,
)
from forgeboard.design.analyzer import (
    DesignAnalyzer,
    DesignAnalysis,
    IdentifiedComponent,
    SketchAnalysis,
    TextAnalysis,
)
from forgeboard.design.wizard import (
    DesignWizard,
    QuestionType,
    WizardQuestion,
    WizardSession,
)

__all__ = [
    # Provider
    "LLMProvider",
    "AnthropicProvider",
    "MockProvider",
    # Analyzer
    "DesignAnalyzer",
    "DesignAnalysis",
    "IdentifiedComponent",
    "SketchAnalysis",
    "TextAnalysis",
    # Wizard
    "DesignWizard",
    "QuestionType",
    "WizardQuestion",
    "WizardSession",
]

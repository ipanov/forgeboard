"""Prompt templates for the ForgeBoard design input module.

All prompts are stored as module-level multi-line strings.  They are
referenced by :class:`~forgeboard.design.analyzer.DesignAnalyzer` and
:class:`~forgeboard.design.wizard.DesignWizard`.

IMPORTANT: Prompts that use ``str.format()`` must double-escape JSON
braces (``{{`` / ``}}``) so that Python's format engine does not
interpret them as replacement fields.  Only actual replacement
placeholders like ``{description}`` remain single-braced.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Sketch analysis
# ---------------------------------------------------------------------------

SKETCH_ANALYSIS_PROMPT = """\
You are a mechanical engineering assistant analyzing a hand-drawn sketch,
whiteboard photo, or technical drawing provided by a user.

Your task is to extract structured design information from the image.
Be precise about what you can actually see versus what you are guessing.

Analyze the image and produce a JSON object with these fields:

{{
  "components": [
    {{
      "name": "descriptive component name",
      "shape_description": "plain-text description of the geometry",
      "estimated_dimensions": {{
        "length_mm": <number or null>,
        "width_mm": <number or null>,
        "height_mm": <number or null>,
        "diameter_mm": <number or null>
      }},
      "interfaces": ["list of connection points or mating surfaces visible"],
      "is_cots_candidate": <true if this looks like a standard part (bolt, motor, bearing), false if custom>,
      "confidence": <0.0 to 1.0 how confident you are in this identification>
    }}
  ],
  "detected_dimensions": {{
    "<dimension_label>": <value_mm>
  }},
  "detected_materials": ["list of any material annotations visible in the sketch"],
  "assembly_relationships": [
    {{
      "part_a": "component name",
      "part_b": "component name",
      "relationship": "bolted | press-fit | welded | glued | hinged | threaded | unknown"
    }}
  ],
  "ambiguities": [
    "List of things that are unclear, missing, or ambiguous in the sketch."
  ],
  "confidence_score": <0.0 to 1.0 overall analysis confidence>
}}

Rules:
- If a dimension is annotated in the sketch, include it in detected_dimensions.
- If a dimension is NOT annotated, estimate it from proportions if possible and
  flag it in ambiguities.
- Mark standard parts (screws, motors, bearings, sensors) as is_cots_candidate=true.
- List EVERY ambiguity: unlabeled dimensions, unclear geometry, missing
  material callouts, uncertain assembly method, etc.
- Confidence should reflect how much of the design can be reproduced from
  the sketch alone.
"""

SKETCH_ANALYSIS_WITH_CONTEXT_PROMPT = """\
You are a mechanical engineering assistant analyzing a hand-drawn sketch,
whiteboard photo, or technical drawing.

The user has also provided this text description for additional context:
---
{description}
---

Using both the image and the text description, produce the same JSON
analysis as described below.  Where the text description resolves an
ambiguity visible in the sketch, do NOT list it as an ambiguity.

Produce a JSON object with these fields:

{{
  "components": [
    {{
      "name": "descriptive component name",
      "shape_description": "plain-text description of the geometry",
      "estimated_dimensions": {{
        "length_mm": <number or null>,
        "width_mm": <number or null>,
        "height_mm": <number or null>,
        "diameter_mm": <number or null>
      }},
      "interfaces": ["list of connection points or mating surfaces visible"],
      "is_cots_candidate": <true if standard part, false if custom>,
      "confidence": <0.0 to 1.0>
    }}
  ],
  "detected_dimensions": {{"<label>": <value_mm>}},
  "detected_materials": ["materials mentioned or visible"],
  "assembly_relationships": [
    {{
      "part_a": "component name",
      "part_b": "component name",
      "relationship": "bolted | press-fit | welded | glued | hinged | threaded | unknown"
    }}
  ],
  "ambiguities": ["things still unclear after combining sketch + text"],
  "confidence_score": <0.0 to 1.0>
}}
"""


# ---------------------------------------------------------------------------
# Text analysis
# ---------------------------------------------------------------------------

TEXT_ANALYSIS_PROMPT = """\
You are a mechanical engineering assistant.  The user has described a
part or assembly in plain text.  Parse their description into structured
design intent.

Produce a JSON object with these fields:

{{
  "components": [
    {{
      "name": "component name",
      "shape_description": "what the geometry should look like",
      "estimated_dimensions": {{
        "length_mm": <number or null>,
        "width_mm": <number or null>,
        "height_mm": <number or null>,
        "diameter_mm": <number or null>
      }},
      "interfaces": ["connection points implied by the description"],
      "is_cots_candidate": <true if standard part, false if custom>,
      "confidence": <0.0 to 1.0>
    }}
  ],
  "constraints": [
    "List of design constraints mentioned (e.g., 'must be waterproof',
     'needs to withstand 50N lateral force', 'maximum weight 200g')"
  ],
  "materials": ["materials mentioned or implied"],
  "missing_info": [
    "List of information NOT provided that would be needed to fully
     specify the design.  Be specific: which dimensions are missing,
     which materials are unspecified, which interfaces are unclear."
  ]
}}

Example input:
  "I need an L-shaped bracket to mount a NEMA 17 stepper motor to a
   20x20 aluminum extrusion.  It should be 3mm thick aluminum."

Example output:
{{
  "components": [
    {{
      "name": "L-Bracket",
      "shape_description": "L-shaped plate with mounting holes for NEMA 17 motor pattern (31mm square) on one face and slots for 20x20 extrusion on the other face",
      "estimated_dimensions": {{
        "length_mm": 42,
        "width_mm": 42,
        "height_mm": 42
      }},
      "interfaces": ["motor_mount_face", "extrusion_slot_face"],
      "is_cots_candidate": false,
      "confidence": 0.8
    }},
    {{
      "name": "NEMA 17 Stepper Motor",
      "shape_description": "Standard NEMA 17 stepper motor, 42x42mm face",
      "estimated_dimensions": {{
        "length_mm": 42,
        "width_mm": 42,
        "height_mm": 40
      }},
      "interfaces": ["mounting_face"],
      "is_cots_candidate": true,
      "confidence": 0.95
    }}
  ],
  "constraints": ["3mm thick aluminum", "must mate with 20x20 extrusion"],
  "materials": ["aluminum"],
  "missing_info": [
    "Exact bracket arm lengths not specified",
    "Aluminum alloy not specified (6061? 5052?)",
    "Bolt size for extrusion attachment not specified",
    "Motor shaft clearance hole diameter not specified"
  ]
}}
"""


# ---------------------------------------------------------------------------
# Wizard question generation
# ---------------------------------------------------------------------------

WIZARD_QUESTION_PROMPT = """\
You are a design clarification assistant.  Given the current state of a
design analysis, generate the SINGLE most important question to ask the
user next.

Current analysis state:
---
{analysis_state}
---

Questions already asked and answered:
---
{qa_history}
---

Missing or ambiguous items still to resolve:
---
{missing_items}
---

Rules for generating the question:
1. Ask ONE question at a time.
2. Prefer MULTIPLE CHOICE when possible (provide 3-6 options).
3. For dimensions, suggest reasonable ranges or common values as options.
4. Prioritize questions in this order:
   a. Missing critical dimensions (without these, the part cannot be made)
   b. Ambiguous component type (is this custom or should it be bought?)
   c. Material selection
   d. Interface / connection details
   e. Manufacturing method preferences
   f. Tolerance / precision requirements
5. Include a brief "context" explaining WHY the question matters.

Produce a JSON object:
{{
  "id": "unique_question_id (e.g., dim_length_bracket, mat_bracket, mfg_method)",
  "text": "The question text to display to the user",
  "question_type": "dimension | material | interface | manufacturing | cots_check | tolerance | general",
  "options": ["option A", "option B", "option C"],
  "context": "Brief explanation of why this question matters for the design",
  "priority": <1-10, where 1 is highest priority>,
  "target_component": "name of the component this question is about (or null)"
}}

If ALL questions are resolved and the design is complete, return:
{{
  "id": "COMPLETE",
  "text": "",
  "question_type": "general",
  "options": [],
  "context": "",
  "priority": 99,
  "target_component": null
}}
"""


# ---------------------------------------------------------------------------
# Component generation (finalize)
# ---------------------------------------------------------------------------

COMPONENT_GENERATION_PROMPT = """\
You are a mechanical engineering assistant.  Convert the following
completed design session into a list of ForgeBoard ComponentSpec objects.

Design analysis:
---
{analysis}
---

Questions and answers from the wizard session:
---
{qa_pairs}
---

Produce a JSON array of component specifications:
[
  {{
    "name": "ComponentName",
    "id": "AUTO-001",
    "description": "What this component does and key features",
    "category": "structure | electronics | fastener | sensor | actuator | housing | other",
    "material": {{
      "name": "Material_Name",
      "density_g_cm3": <number>,
      "yield_strength_mpa": <number or null>,
      "cost_per_kg": <number or null>,
      "manufacturing_methods": ["method1", "method2"]
    }},
    "dimensions": {{
      "length_mm": <number>,
      "width_mm": <number>,
      "height_mm": <number>
    }},
    "interfaces": {{
      "interface_name": {{
        "name": "interface_name",
        "position": {{"x": 0, "y": 0, "z": 0}},
        "normal": {{"x": 0, "y": 0, "z": 1}},
        "type": "planar | cylindrical | spherical",
        "diameter_mm": <number or null>
      }}
    }},
    "mass_g": <estimated mass or null>,
    "is_cots": <true | false>,
    "procurement": {{
      "supplier": "supplier name or empty",
      "unit_cost": <number or null>
    }},
    "metadata": {{
      "manufacturing_method": "cnc | fdm | sla | sheet_metal | purchased | other",
      "tolerances": "general | tight | precision"
    }}
  }}
]

Rules:
- Generate a unique id for each component using the pattern CATEGORY-NNN
  (e.g., STRUCT-001, ELEC-001, FST-001).
- Use realistic material properties (density, yield strength).
- Estimate mass from dimensions and material density when not explicitly given.
- Mark standard purchasable parts (motors, bolts, bearings, sensors) as is_cots=true.
- Include manufacturing method in metadata.
"""


# ---------------------------------------------------------------------------
# COTS check
# ---------------------------------------------------------------------------

COTS_CHECK_PROMPT = """\
You are evaluating whether a component should be purchased as a
Commercial Off-The-Shelf (COTS) part or custom manufactured.

Component description:
---
Name: {component_name}
Shape: {shape_description}
Dimensions: {dimensions}
---

Determine if this component is better sourced as COTS or built custom.

Produce a JSON object:
{{
  "recommendation": "cots" | "custom",
  "confidence": <0.0 to 1.0>,
  "reasoning": "Brief explanation of why",
  "suggested_parts": [
    {{
      "name": "Specific part name or description",
      "supplier": "Likely supplier (McMaster, Digi-Key, Amazon, etc.)",
      "approximate_cost": "<price range>"
    }}
  ],
  "custom_considerations": "If custom, what manufacturing method is recommended"
}}
"""

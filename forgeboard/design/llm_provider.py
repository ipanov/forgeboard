"""LLM provider abstraction for ForgeBoard design input.

Defines the :class:`LLMProvider` protocol that all AI backends must
satisfy, plus concrete implementations:

- :class:`AnthropicProvider` -- wraps the Anthropic (Claude) API.
  Requires ``pip install forgeboard[llm]``.
- :class:`MockProvider` -- deterministic stub for unit testing.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract LLM interface.

    Implementations wrap a specific AI provider (Anthropic, OpenAI, Google,
    local models, etc.).  ForgeBoard calls only these three methods, so any
    vision-capable model can be plugged in.
    """

    def generate(self, prompt: str, system: str = "") -> str:
        """Generate text from a prompt.

        Parameters
        ----------
        prompt:
            The user-facing message or question.
        system:
            An optional system prompt that sets context and behaviour.

        Returns
        -------
        str
            The model's text response.
        """
        ...

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Analyze an image with a text prompt (vision).

        Parameters
        ----------
        image_path:
            Filesystem path to the image (PNG, JPEG, WebP, etc.).
        prompt:
            Instructions describing what to extract or identify.

        Returns
        -------
        str
            The model's text response about the image.
        """
        ...

    def structured_output(
        self, prompt: str, schema: dict[str, Any], system: str = ""
    ) -> dict[str, Any]:
        """Generate structured JSON output matching a schema.

        Parameters
        ----------
        prompt:
            The user-facing request.
        schema:
            A JSON Schema dict describing the expected output structure.
        system:
            An optional system prompt.

        Returns
        -------
        dict
            A Python dict conforming to *schema*.
        """
        ...


# ---------------------------------------------------------------------------
# Anthropic (Claude) provider
# ---------------------------------------------------------------------------


def _image_media_type(path: str) -> str:
    """Infer MIME type from file extension."""
    suffix = Path(path).suffix.lower()
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mapping.get(suffix, "image/png")


class AnthropicProvider:
    """Claude API provider.

    Requires ``pip install forgeboard[llm]`` which pulls in the
    ``anthropic`` package.  The API key is read from the
    ``ANTHROPIC_API_KEY`` environment variable unless passed explicitly.

    Parameters
    ----------
    api_key:
        Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
    model:
        Model identifier.  Defaults to ``claude-sonnet-4-20250514``.
    max_tokens:
        Maximum tokens per response.  Defaults to 4096.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ) -> None:
        try:
            import anthropic  # noqa: F811
        except ImportError as exc:
            raise ImportError(
                "The Anthropic provider requires the 'anthropic' package. "
                "Install it with: pip install forgeboard[llm]"
            ) from exc

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "No Anthropic API key provided. Pass api_key= or set the "
                "ANTHROPIC_API_KEY environment variable."
            )
        self._client = anthropic.Anthropic(api_key=resolved_key)
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, prompt: str, system: str = "") -> str:
        """Generate text from a prompt using Claude."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        return response.content[0].text  # type: ignore[union-attr]

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Analyze an image using Claude's vision capability."""
        image_data = Path(image_path).read_bytes()
        b64_data = base64.standard_b64encode(image_data).decode("ascii")
        media_type = _image_media_type(image_path)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            },
        ]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,
        )
        return response.content[0].text  # type: ignore[union-attr]

    def structured_output(
        self, prompt: str, schema: dict[str, Any], system: str = ""
    ) -> dict[str, Any]:
        """Generate structured JSON output from Claude.

        Instructs the model to respond with valid JSON matching the
        provided schema.  The schema is embedded in the system prompt
        and the raw response is parsed with ``json.loads``.
        """
        schema_instruction = (
            "You MUST respond with valid JSON and nothing else. "
            "No markdown fences, no commentary, just the JSON object.\n\n"
            f"Required JSON schema:\n{json.dumps(schema, indent=2)}"
        )
        full_system = f"{system}\n\n{schema_instruction}" if system else schema_instruction

        raw = self.generate(prompt, system=full_system)

        # Strip markdown fences if the model includes them despite instructions.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        return json.loads(cleaned)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Mock provider (for testing)
# ---------------------------------------------------------------------------


class MockProvider:
    """Mock LLM provider for testing.

    Returns predefined responses keyed by prompt substrings. When no
    match is found, returns a generic fallback.

    Parameters
    ----------
    responses:
        Mapping of prompt-substring to response string.  The first
        matching key (checked in insertion order) wins.
    structured_responses:
        Mapping of prompt-substring to dict.  Used by
        :meth:`structured_output`.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        structured_responses: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._responses: dict[str, str] = responses or {}
        self._structured: dict[str, dict[str, Any]] = structured_responses or {}
        self.call_log: list[dict[str, Any]] = []

    def generate(self, prompt: str, system: str = "") -> str:
        """Return the first matching predefined response."""
        self.call_log.append(
            {"method": "generate", "prompt": prompt, "system": system}
        )
        for key, value in self._responses.items():
            if key in prompt:
                return value
        return '{"result": "mock response"}'

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Return the first matching predefined response for image analysis."""
        self.call_log.append(
            {"method": "analyze_image", "image_path": image_path, "prompt": prompt}
        )
        for key, value in self._responses.items():
            if key in prompt:
                return value
        return '{"components": [], "ambiguities": ["mock analysis"]}'

    def structured_output(
        self, prompt: str, schema: dict[str, Any], system: str = ""
    ) -> dict[str, Any]:
        """Return the first matching predefined structured response."""
        self.call_log.append(
            {
                "method": "structured_output",
                "prompt": prompt,
                "schema": schema,
                "system": system,
            }
        )
        for key, value in self._structured.items():
            if key in prompt:
                return value
        # Fallback: return an empty dict matching the schema's top-level keys.
        if "properties" in schema:
            return {k: _default_for_schema(v) for k, v in schema["properties"].items()}
        return {}


def _default_for_schema(prop: dict[str, Any]) -> Any:
    """Produce a trivial default value for a JSON schema property."""
    t = prop.get("type", "string")
    if t == "string":
        return ""
    if t == "number" or t == "integer":
        return 0
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return None

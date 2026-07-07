"""
Character schema and validation using Pydantic.

This validates the *actual* on-disk format used by `data/characters/*/index.yaml`
(a flat structure — see backend/core/config/settings.py:_DEFAULT_CHARACTER for
the canonical field set). It is invoked from `_scan_characters_in()` so a
malformed character file produces a clear validation error at load time
instead of silently propagating bad data (missing mood bounds, wrong types,
etc.) into the agent/relationship/TTS layers downstream.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class CharacterSchema(BaseModel):
    """Validates one character's `index.yaml`, post-merge with defaults.

    Fields populated dynamically by the loader (icon_url, model_url, _dir,
    voice_ref) are accepted but not required, since they don't come from the
    YAML file itself.
    """

    # Identity
    name: str = Field(..., min_length=1, max_length=100, description="Character name")
    description: str = Field(default="", max_length=500, description="Short description")

    # Personality
    personality: str = Field(default="helpful", description="Personality tag/slug")
    characteristics: str = Field(default="helpful", description="Comma-separated traits")
    interaction_style: str = Field(default="direct", description="How the character interacts")
    vocabulary: List[str] = Field(default_factory=list, description="Favorite phrases")
    dialogue_examples: List[str] = Field(default_factory=list, description="Example exchanges")

    # Behavior constraints
    quirks: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list, description="Behaviors to never exhibit")
    memory_bias: List[str] = Field(default_factory=list)

    # LLM + voice
    system_prompt: str = Field(
        default="You are a helpful and friendly assistant.",
        min_length=10,
        max_length=4000,
        description="System prompt for LLM instruction",
    )
    voice: str = Field(default="en-US-AriaNeural", description="TTS voice ID")
    greeting: Optional[str] = Field(default=None, max_length=500)

    # Relationship / mood
    mood_baseline: float = Field(default=0.5, ge=0.0, le=1.0)
    mood_volatility: float = Field(default=0.3, ge=0.0, le=1.0)

    # Populated by the loader, not user-authored — accepted as pass-through.
    icon_url: Optional[str] = None
    model_url: Optional[str] = None
    voice_ref: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("vocabulary", "dialogue_examples", "quirks", "forbidden",
                      "memory_bias", mode="before")
    @classmethod
    def _ensure_list(cls, v):
        """Allow a bare string in the YAML to count as a one-item list."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("voice", mode="before")
    @classmethod
    def _voice_to_str(cls, v):
        """Tolerate a nested {voice_id: ...} dict for forward-compatibility,
        but the canonical on-disk shape is a plain string."""
        if isinstance(v, dict):
            return v.get("voice_id", "en-US-AriaNeural")
        return v

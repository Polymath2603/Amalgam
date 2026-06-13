"""
Character schema and validation using Pydantic.

Defines the structure and validation for character definitions including:
- Personality and interaction style
- Voice and TTS configuration
- VRM model and animation management
- Relationship and mood settings
"""

from pydantic import BaseModel, Field, field_validator, PrivateAttr
from typing import Optional, List, Dict, Any
from enum import Enum


class VoiceConfig(BaseModel):
    """Voice configuration for a character."""
    engine: str = Field(default="edge-tts", description="TTS engine (edge-tts, openvoice, etc)")
    voice_id: str = Field(default="en-US-AriaNeural", description="Voice ID for the engine")
    voice_ref: Optional[str] = Field(default=None, description="Path to reference voice for OpenVoice")
    pitch: float = Field(default=1.0, ge=0.5, le=2.0, description="Voice pitch multiplier")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    emotion_prosody: bool = Field(default=True, description="Use emotion-aware prosody in TTS")


class VRMConfig(BaseModel):
    """VRM model and animation configuration."""
    model_url: str = Field(default="", description="URL to VRM model file")
    half_body_mode: bool = Field(default=False, description="Use bust-shot camera for mobile portrait")
    default_idle_animation: str = Field(default="idle_loop.vrma", description="Default idle animation file")
    animations: Dict[str, str] = Field(default_factory=dict, description="Named animation mappings")
    animation_scale: float = Field(default=1.0, ge=0.5, le=2.0, description="Animation playback speed")
    
    @field_validator('model_url')
    @classmethod
    def validate_model_url(cls, v: str) -> str:
        """Validate that model_url is a valid VRM path."""
        if v and not v.endswith('.vrm'):
            raise ValueError('model_url must end with .vrm')
        return v


class RelationshipConfig(BaseModel):
    """Relationship tracking configuration."""
    enabled: bool = Field(default=True, description="Enable relationship tracking for this character")
    mood_baseline: float = Field(default=0.5, ge=0.0, le=1.0, description="Baseline mood sentiment")
    mood_volatility: float = Field(default=0.3, ge=0.0, le=1.0, description="Mood change sensitivity")
    stage_progression: bool = Field(default=True, description="Enable relationship stage progression")


class CharacterSchema(BaseModel):
    """Complete character definition schema."""
    # Identity
    name: str = Field(..., min_length=1, max_length=100, description="Character name")
    id: Optional[str] = Field(default=None, description="Character ID (auto-generated from name)")
    description: str = Field(default="", description="Character description")
    icon_url: str = Field(default="/icons/logo.png", description="URL to character icon")
    
    # Personality
    personality: str = Field(default="helpful", description="Personality traits (comma-separated)")
    characteristics: str = Field(default="helpful", description="Character characteristics")
    interaction_style: str = Field(default="direct", description="How the character interacts")
    vocabulary: List[str] = Field(default_factory=list, description="Favorite phrases and catchphrases")
    dialogue_examples: List[str] = Field(default_factory=list, description="Example dialogue patterns")
    
    # Behavior constraints
    quirks: List[str] = Field(default_factory=list, description="Character quirks and habits")
    forbidden: List[str] = Field(default_factory=list, description="Behaviors to never exhibit")
    
    # System and voice
    system_prompt: str = Field(
        default="You are a helpful and friendly assistant.",
        description="System prompt for LLM instruction"
    )
    voice: VoiceConfig = Field(default_factory=VoiceConfig, description="Voice configuration")
    
    # VRM model and animation
    vrm: VRMConfig = Field(default_factory=VRMConfig, description="VRM model configuration")
    
    # Relationship
    relationship: RelationshipConfig = Field(
        default_factory=RelationshipConfig,
        description="Relationship tracking configuration"
    )
    
    # Internal metadata (not user-editable) - using PrivateAttr for Pydantic v2 compatibility
    _dir: str = PrivateAttr(default="")
    _version: str = PrivateAttr(default="1.0")
    
    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "name": "Assistant",
                "personality": "warm, helpful, curious",
                "characteristics": "friendly, knowledgeable, patient",
                "interaction_style": "engaging, detailed",
                "system_prompt": "You are a warm and helpful AI assistant.",
                "voice": {
                    "engine": "edge-tts",
                    "voice_id": "en-US-AriaNeural",
                    "pitch": 1.0,
                    "speed": 1.0,
                },
                "vrm": {
                    "model_url": "/characters/assistant/model.vrm",
                    "half_body_mode": False,
                },
                "relationship": {
                    "enabled": True,
                    "mood_baseline": 0.5,
                    "mood_volatility": 0.3,
                },
            }
        }
    
    def validate_system_prompt(self) -> None:
        """Validate that system prompt is reasonable length and content."""
        if len(self.system_prompt) < 10:
            raise ValueError("system_prompt must be at least 10 characters")
        if len(self.system_prompt) > 2000:
            raise ValueError("system_prompt must not exceed 2000 characters")
    
    @field_validator('vocabulary', 'dialogue_examples', 'quirks', 'forbidden', mode='before')
    @classmethod
    def ensure_list(cls, v):
        """Ensure fields are lists."""
        if isinstance(v, str):
            return [v]
        if v is None:
            return []
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding internal fields."""
        data = self.model_dump(exclude={'_dir', '_version'})
        return data
    
    def with_directory(self, dir_path: str) -> 'CharacterSchema':
        """Create a copy with directory path set."""
        self._dir = dir_path
        return self

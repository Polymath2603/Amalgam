"""
Emotion Analyzer Plugin — Example plugin for Amalgam.

Analyzes text for emotional content and provides sentiment scores.
Demonstrates:
- Custom tools provided to the LLM
- Hooks into response processing
- Integration with external libraries (VADER sentiment)
"""

import logging
from typing import Any, Dict, Optional

from backend.plugins.base import BasePlugin, PluginMetadata, PluginTool

logger = logging.getLogger(__name__)

__all__ = ["EmotionAnalyzerPlugin", "PluginClass"]


class EmotionAnalyzerPlugin(BasePlugin):
    """Analyzes text for emotional content."""

    def __init__(
        self, config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the emotion analyzer plugin.

        Args:
            config: Optional configuration dict. Supported keys:
                - ``nltk_data_path``: Custom path for NLTK data.
        """
        metadata = PluginMetadata(
            name="emotion_analyzer",
            version="1.0.0",
            author="Amalgam",
            description="Analyzes text for emotional sentiment and tone",
            tags=["sentiment", "analysis", "emotion"],
        )
        super().__init__(metadata, config=config)
        self.sia = None

    async def initialize(self) -> None:
        """Initialize the plugin — lazy-import NLTK and download model."""
        await self._init_sentiment_analyzer()
        # super().initialize() calls on_initialize() which registers tools
        await super().initialize()

    async def _init_sentiment_analyzer(self) -> None:
        """Lazy-import and set up VADER sentiment."""
        try:
            import nltk
            from nltk.sentiment import SentimentIntensityAnalyzer

            # Allow configuring the NLTK data path
            nltk_data_path = (self.config or {}).get("nltk_data_path")
            if nltk_data_path:
                nltk.data.path.insert(0, nltk_data_path)

            # Download model (silent, only if missing)
            nltk.download("vader_lexicon", quiet=True)
            self.sia = SentimentIntensityAnalyzer()
            logger.info("Emotion Analyzer initialized")
        except Exception as e:
            logger.error(
                "Failed to initialize Emotion Analyzer: %s", e
            )

    async def on_initialize(self) -> None:
        """Register tools provided by this plugin."""
        analyze_tool = PluginTool(
            name="analyze_emotion",
            description="Analyze the emotional content of text",
            func=self.analyze_emotion,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to analyze",
                    }
                },
                "required": ["text"],
            },
        )
        self.register_tool(analyze_tool)

    async def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        self.sia = None
        logger.info("Emotion Analyzer shut down")

    async def analyze_emotion(
        self, text: str
    ) -> Dict[str, Any]:
        """Analyze emotion in text.

        Args:
            text: Text to analyze.

        Returns:
            Dict with sentiment scores and emotion classification.
        """
        if not self.sia:
            return {"error": "Emotion analyzer not initialized"}

        scores = self.sia.polarity_scores(text)

        # Classify emotion based on compound score
        compound = scores["compound"]
        if compound >= 0.5:
            emotion = "positive"
        elif compound <= -0.5:
            emotion = "negative"
        else:
            emotion = "neutral"

        return {
            "emotion": emotion,
            "scores": {
                "positive": scores["pos"],
                "negative": scores["neg"],
                "neutral": scores["neu"],
                "compound": scores["compound"],
            },
        }

    async def on_before_response(
        self, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze user input before generating response.

        Args:
            context: Conversation context.

        Returns:
            Modified context with emotion analysis.
        """
        if "user_message" in context and self.sia:
            user_msg = context["user_message"]
            emotion_data = await self.analyze_emotion(user_msg)
            context["user_emotion"] = emotion_data

        return context


# Entry point discovered by PluginManager
PluginClass = EmotionAnalyzerPlugin

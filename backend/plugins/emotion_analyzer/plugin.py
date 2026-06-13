"""
Emotion Analyzer Plugin - Example plugin for Amalgam.

Analyzes text for emotional content and provides sentiment scores.
Demonstrates:
- Custom tools provided to the LLM
- Hooks into response processing
- Integration with external libraries (VADER sentiment)
"""

from nltk.sentiment import SentimentIntensityAnalyzer
import logging
from typing import Dict, Any

from backend.plugins.base import BasePlugin, PluginMetadata, PluginTool

logger = logging.getLogger(__name__)


class EmotionAnalyzerPlugin(BasePlugin):
    """Analyzes text for emotional content."""
    
    def __init__(self):
        """Initialize the emotion analyzer plugin."""
        metadata = PluginMetadata(
            name="emotion_analyzer",
            version="1.0.0",
            author="Amalgam",
            description="Analyzes text for emotional sentiment and tone",
            tags=["sentiment", "analysis", "emotion"],
        )
        super().__init__(metadata)
        self.sia = None
    
    async def initialize(self):
        """Initialize the plugin - download VADER lexicon if needed."""
        try:
            import nltk
            nltk.download('vader_lexicon', quiet=True)
            self.sia = SentimentIntensityAnalyzer()
            logger.info("Emotion Analyzer initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Emotion Analyzer: {e}")
    
    async def on_initialize(self):
        """Register tools when initializing."""
        analyze_tool = PluginTool(
            name="analyze_emotion",
            description="Analyze the emotional content of text",
            func=self.analyze_emotion,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to analyze"
                    }
                },
                "required": ["text"]
            }
        )
        self.register_tool(analyze_tool)
    
    async def analyze_emotion(self, text: str) -> Dict[str, Any]:
        """Analyze emotion in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dict with sentiment scores and emotion classification
        """
        if not self.sia:
            return {"error": "Emotion analyzer not initialized"}
        
        scores = self.sia.polarity_scores(text)
        
        # Classify emotion based on compound score
        compound = scores['compound']
        if compound >= 0.5:
            emotion = 'positive'
        elif compound <= -0.5:
            emotion = 'negative'
        else:
            emotion = 'neutral'
        
        return {
            "emotion": emotion,
            "scores": {
                "positive": scores['pos'],
                "negative": scores['neg'],
                "neutral": scores['neu'],
                "compound": scores['compound'],
            }
        }
    
    async def on_before_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze user input before generating response.
        
        Args:
            context: Conversation context
            
        Returns:
            Modified context with emotion analysis
        """
        if 'user_message' in context and self.sia:
            user_msg = context['user_message']
            emotion_data = await self.analyze_emotion(user_msg)
            context['user_emotion'] = emotion_data
        
        return context


# This is the entry point for the plugin system
PluginClass = EmotionAnalyzerPlugin

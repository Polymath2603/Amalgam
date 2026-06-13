"""Example plugin demonstrating the plugin registration API."""

import logging

logger = logging.getLogger(__name__)


def register() -> dict:
    """Return plugin metadata and hook bindings."""
    return {
        "name": "example",
        "version": "0.1.0",
        "description": "An example plugin that logs every user message.",
        "hooks": ["pre_process", "post_process"],
        "init": _init,
    }


def _init(config: dict = None):
    """Optional initialisation called when the plugin is loaded."""
    logger.info("Example plugin initialised with config: %s", config)


async def pre_process(text: str, **kwargs) -> str:
    """Hook: called before the agent processes user input."""
    logger.debug("ExamplePlugin.pre_process: %s", text[:50])
    return text


async def post_process(response: str, **kwargs) -> str:
    """Hook: called after the agent produces a response."""
    logger.debug("ExamplePlugin.post_process: %d chars", len(response))
    return response

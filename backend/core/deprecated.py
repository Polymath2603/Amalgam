"""
Deprecation helpers for marking unused endpoints.

These endpoints exist in the backend but have zero frontend consumers.
They are deprecated and will be removed in a future release.
"""
import functools
import logging
import asyncio


def deprecated(alternative: str = ""):
    """Decorator marking an endpoint as deprecated (unused by frontend).

    Logs a warning on each call. Works with both sync and async handlers.

    Usage:
        @router.get("/api/foo")
        @deprecated()
        async def my_endpoint():
            ...
    """
    msg = "DEPRECATED: This endpoint has zero frontend consumers and will be removed"
    if alternative:
        msg += f". Use {alternative} instead"

    def decorator(func):
        logger = logging.getLogger(func.__module__)

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.warning(msg)
                return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.warning(msg)
                return func(*args, **kwargs)
            return sync_wrapper

    return decorator

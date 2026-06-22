"""Redirect to backend.core.agent.permissions.

The real PermissionGate is in backend.core.agent.permissions.
This module is kept as a redirect to avoid breaking any potential imports.
"""
from backend.core.agent.permissions import *  # noqa: F401, F403

"""Self-learning module — persistent learning, skill creation, and adaptation.

Following the Hermes Agent pattern, this module enables the system to:
- Auto-create reusable skills from novel problem solutions
- Learn from user corrections
- Infer preferences from interaction patterns
- Aggregate cross-session context
- Adapt behavior based on user engagement
- Periodically review and improve the skill library
- Use metrics data to drive optimization decisions
"""

from backend.core.self_learning.auto_skill import AutoSkillCreator
from backend.core.self_learning.corrections import CorrectionStore
from backend.core.self_learning.preferences import PreferenceLearner
from backend.core.self_learning.improvement import SkillImprover

__all__ = [
    "AutoSkillCreator",
    "CorrectionStore",
    "PreferenceLearner",
    "SkillImprover",
]

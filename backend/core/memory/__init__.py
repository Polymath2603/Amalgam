"""
Memory subsystem — five functional partitions, not five identically-named
files:

  - Working    -> working.py (WorkingMemory): recent conversation turns,
                  bounded capacity, no persistence.
  - Episodic   -> episodic.py (EpisodicMemory), one per session, retrieved
                  via Memory._get_episodic(session_id): what happened, when.
  - Semantic   -> semantic.py (SemanticMemory) + hybrid.py/fts.py: facts and
                  their embeddings/keyword index, independent of when they
                  were learned.
  - Procedural -> backend/skills/ + backend/core/skills/curator.py: *how* to
                  do things, stored as reusable SKILL.md definitions that
                  get created, graded, merged, and pruned over time. This is
                  procedural memory's natural home — duplicating it here as
                  a thin "procedural.py" wrapper would just fragment the
                  same concept across two places.
  - User model -> backend/core/user_profile.py (UserProfile): accumulated
                  preferences/expertise/recurring-task patterns, persisted
                  across sessions independently of any one fact or skill.

`Memory` (manager.py) is the façade that ties working/episodic/semantic
together; procedural and user-model memory are deliberately separate
modules rather than nested under this package, since skills and the user
profile are used by callers (e.g. the orchestrator, the CLI) that don't
need the rest of the memory stack.
"""
from backend.core.memory.cache import FACTCache
from backend.core.memory.hybrid import HybridRetrieval
from backend.core.memory.session_index import SessionIndex
from backend.core.memory.manager import Memory
from backend.core.memory.working import WorkingMemory
from backend.core.memory.episodic import EpisodicMemory
from backend.core.memory.semantic import SemanticMemory
from backend.core.memory.consolidator import Consolidator
from backend.core.memory.fts import FTSSearch

__all__ = ["FACTCache", "HybridRetrieval", "SessionIndex", "Memory",
           "WorkingMemory", "EpisodicMemory", "SemanticMemory", "Consolidator",
           "FTSSearch"]

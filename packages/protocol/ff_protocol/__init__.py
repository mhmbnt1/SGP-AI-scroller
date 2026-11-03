"""FocusFeed shared protocol.

These DTOs are the contract between the API/worker and the local collector.
They are deliberately dependency-light (pydantic only) so the collector can
run on a user's Windows machine without the backend stack installed.
"""

from ff_protocol.models import (
    AdapterCapabilities,
    AnalysisKind,
    CandidateItem,
    CollectionMode,
    CollectorJobInstruction,
    CollectorJobResult,
    CollectorResultState,
    EvidenceBundle,
    FrameSample,
    JobBudget,
    Platform,
    PlatformResult,
    SessionStatus,
    TranscriptSegment,
    TranscriptSource,
)

__all__ = [
    "AdapterCapabilities",
    "AnalysisKind",
    "CandidateItem",
    "CollectionMode",
    "CollectorJobInstruction",
    "CollectorJobResult",
    "CollectorResultState",
    "EvidenceBundle",
    "FrameSample",
    "JobBudget",
    "Platform",
    "PlatformResult",
    "SessionStatus",
    "TranscriptSegment",
    "TranscriptSource",
]

PROTOCOL_VERSION = "1.0"

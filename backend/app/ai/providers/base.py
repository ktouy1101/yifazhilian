from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """A public-safe error: never retain upstream body, credentials or request."""

    def __init__(self, status_code: int, safe_message: str):
        self.status_code = status_code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    domain: str
    title: str
    text: str
    url: str | None
    keywords: tuple[str, ...]
    source_id: str | None = None
    source_title: str | None = None
    version: str = "1"
    status: str = "published"
    effective_from: str | None = None
    effective_until: str | None = None
    reviewed_by: str | None = None


class AIProvider(Protocol):
    """Adapters receive only approved text, never the patient record or token.

    Only one synthetic question and domain-matched reference text may leave.
    Never pass patient records, session IDs, tokens or conversation history.
    """

    name: str
    external_network: bool
    recipient: str
    policy_version: str
    consent_notice: str

    def generate(self, *, domain: str, text: str,
                 context: list[KnowledgeChunk]) -> str: ...

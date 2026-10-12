from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    domain: str
    title: str
    text: str
    url: str | None
    keywords: tuple[str, ...]


class AIProvider(Protocol):
    """Adapters receive only approved text, never the patient record or token.

    Future adapters for Qwen, ERNIE or DeepSeek implement this boundary.
    Provider egress, consent, redaction, residency and contracts require review
    before any external adapter may be enabled. This build has none.
    """

    name: str

    def generate(self, *, domain: str, text: str,
                 context: list[KnowledgeChunk]) -> str: ...

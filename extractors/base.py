from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobPost:
    title: str
    company: str
    link: str
    description: str
    date_posted: str
    source: str
    location: Optional[str] = field(default=None)

    def __str__(self) -> str:
        lines = [
            f"  Title      : {self.title}",
            f"  Company    : {self.company}",
            f"  Location   : {self.location or 'N/A'}",
            f"  Date Posted: {self.date_posted}",
            f"  Source     : {self.source}",
            f"  Link       : {self.link}",
            f"  Description: {self.description[:200].strip()}{'...' if len(self.description) > 200 else ''}",
        ]
        return "\n".join(lines)


class JobExtractor(ABC):
    """Base class all source-specific extractors must implement."""

    @abstractmethod
    def fetch(self, limit: int = 10) -> list[JobPost]:
        """Fetch up to `limit` jobs from the source and return standardised JobPost objects."""
        raise NotImplementedError

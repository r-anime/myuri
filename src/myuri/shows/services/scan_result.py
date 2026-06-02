from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class FoundEpisode:
    """Represents an episode found during a scan."""
    show_id: int
    show_title: str
    episode_number: int
    source: str  # e.g., "Nyaa"
    source_title: str
    found_at: datetime
    link: str


@dataclass
class ScanResult:
    """Results from a scan operation."""
    scan_time: datetime
    episodes_found: List[FoundEpisode] = field(default_factory=list)
    shows_scanned: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "scan_time": self.scan_time.isoformat(),
            "episodes_found": [
                {
                    "show_id": ep.show_id,
                    "show_title": ep.show_title,
                    "episode_number": ep.episode_number,
                    "source": ep.source,
                    "source_title": ep.source_title,
                    "found_at": ep.found_at.isoformat(),
                    "link": ep.link,
                }
                for ep in self.episodes_found
            ],
            "shows_scanned": self.shows_scanned,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScanResult":
        """Create from dictionary (for session deserialization)."""
        return cls(
            scan_time=datetime.fromisoformat(data["scan_time"]),
            episodes_found=[
                FoundEpisode(
                    show_id=ep["show_id"],
                    show_title=ep["show_title"],
                    episode_number=ep["episode_number"],
                    source=ep["source"],
                    source_title=ep["source_title"],
                    found_at=datetime.fromisoformat(ep["found_at"]),
                    link=ep["link"],
                )
                for ep in data.get("episodes_found", [])
            ],
            shows_scanned=data.get("shows_scanned", 0),
            errors=data.get("errors", []),
        )

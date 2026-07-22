"""Service for automatically posting eligible episodes after scanning."""
from dataclasses import dataclass, field
from typing import List, Optional

from .scan_result import ScanResult


@dataclass
class EpisodeEligibility:
    """Represents the eligibility status of a scanned episode for posting."""
    show_id: int
    show_title: str
    scanned_episode: int
    latest_db_episode: Optional[str]  # None if no episodes exist
    is_eligible: bool
    reason: str  # "ready_to_post", "not_next_episode", "already_posted", etc.
    sources: List[str] = field(default_factory=list)  # e.g. ["Nyaa", "Nekobt"]


@dataclass
class AutoPostResult:
    """Results from auto-posting eligible episodes."""
    posted: List[dict]  # [{show_id, show_title, episode, url}]
    skipped: List[dict]  # [{show_id, show_title, episode, reason}]
    failed: List[dict]  # [{show_id, show_title, episode, error}]


class AutoPostService:
    """Service for determining eligibility and posting episodes."""

    def __init__(self):
        self._reddit_service = None
        self._notification_service = None

    @property
    def reddit_service(self):
        """Lazy-load RedditService to avoid requiring praw at import time."""
        if self._reddit_service is None:
            from .reddit_service import RedditService
            self._reddit_service = RedditService()
        return self._reddit_service

    @property
    def notification_service(self):
        """Lazy-load NotificationService."""
        if self._notification_service is None:
            from .notification_service import NotificationService
            self._notification_service = NotificationService()
        return self._notification_service

    def determine_eligibility(self, scan_result: ScanResult) -> List[EpisodeEligibility]:
        """
        Analyze scan results and determine which episodes are eligible for posting.

        Eligibility rules:
        - If no episodes exist for a show, the lowest-numbered episode found is eligible
        - Each subsequent episode in the same scan is eligible only if it is exactly
          pending_latest + 1 (chaining within a single scan)
        - If episodes exist in DB, scanned episode must be exactly latest + 1
        """
        from ..models import Show

        eligibilities = []
        # Tracks the highest episode number marked eligible per show in this run,
        # so that subsequent episodes in the same scan are evaluated against it
        # rather than the stale DB state.
        pending_latest: dict = {}  # {show_id: episode_number}

        # Group by (show_id, episode_number) so that when multiple scanners find
        # the same episode, they collapse into a single eligibility check whose
        # `sources` lists every contributing scanner, instead of one entry per
        # scanner. Sort by key so lower-numbered episodes are always evaluated
        # first; this ensures correct order assignment when multiple episodes for
        # the same show appear in a single scan.
        groups = scan_result.group_by_episode()

        for key in sorted(groups.keys()):
            group = groups[key]
            found = group[0]
            sources = sorted(set(f.source for f in group))
            try:
                show = Show.objects.get(id=found.show_id)
            except Show.DoesNotExist:
                continue

            # Get latest non-special episode from DB (exclude removed episodes)
            latest = show.episodes.filter(is_special=False, scheduled_for_removal=False).order_by("-order").first()

            if latest is None:
                db_latest_num = None
                latest_str = None
            else:
                try:
                    db_latest_num = int(latest.number)
                    latest_str = latest.number
                except ValueError:
                    eligibilities.append(EpisodeEligibility(
                        show_id=found.show_id,
                        show_title=found.show_title,
                        scanned_episode=found.episode_number,
                        latest_db_episode=latest.number,
                        is_eligible=False,
                        reason=f"non_numeric_latest (latest is '{latest.number}')",
                        sources=sources,
                    ))
                    continue

            # Effective latest is whichever is higher: DB or pending from this scan
            if found.show_id in pending_latest:
                effective_latest = max(pending_latest[found.show_id], db_latest_num or 0)
            else:
                effective_latest = db_latest_num  # may be None

            if effective_latest is None:
                # No episodes in DB and none pending - this is the first episode
                is_eligible = True
                reason = "ready_to_post"
                pending_latest[found.show_id] = found.episode_number
            else:
                expected_next = effective_latest + 1
                if found.episode_number == expected_next:
                    is_eligible = True
                    reason = "ready_to_post"
                    pending_latest[found.show_id] = found.episode_number
                elif found.episode_number <= effective_latest:
                    is_eligible = False
                    reason = f"already_posted (latest is {effective_latest})"
                else:
                    is_eligible = False
                    reason = f"gap_detected (found {found.episode_number}, expected {expected_next})"

            eligibilities.append(EpisodeEligibility(
                show_id=found.show_id,
                show_title=found.show_title,
                scanned_episode=found.episode_number,
                latest_db_episode=latest_str,
                is_eligible=is_eligible,
                reason=reason,
                sources=sources,
            ))

        return eligibilities

    def post_eligible_episodes(self, eligibilities: List[EpisodeEligibility]) -> AutoPostResult:
        """
        Post all eligible episodes to Reddit and create Episode records.

        Returns detailed results with posted, skipped, and failed episodes.
        """
        from ..models import Show, Episode
        from django.utils import timezone

        posted = []
        skipped = []
        failed = []

        # Process in episode-number order so that order values are assigned
        # correctly when multiple episodes for the same show are posted in one run.
        for eligible_episode in sorted(eligibilities, key=lambda e: (e.show_id, e.scanned_episode)):
            if not eligible_episode.is_eligible:
                skipped.append({
                    "show_id": eligible_episode.show_id,
                    "show_title": eligible_episode.show_title,
                    "episode": eligible_episode.scanned_episode,
                    "reason": eligible_episode.reason,
                })
                continue

            try:
                show = Show.objects.get(id=eligible_episode.show_id)
                episode_number = str(eligible_episode.scanned_episode)

                # Calculate order (same logic as fire_next_episode)
                last_episode = show.episodes.filter(scheduled_for_removal=False).order_by("-order").first()
                next_order = (last_episode.order + 1) if last_episode else 1

                # Check if final episode
                is_final = False
                if show.episode_count:
                    is_final = eligible_episode.scanned_episode >= show.episode_count

                # Post to Reddit
                result = self.reddit_service.submit_episode_post(show, episode_number, is_final)

                # Create Episode record
                Episode.objects.create(
                    show=show,
                    number=episode_number,
                    order=next_order,
                    air_date=timezone.now(),
                    discussion_url=result["url"],
                )

                posted.append({
                    "show_id": eligible_episode.show_id,
                    "show_title": eligible_episode.show_title,
                    "episode": eligible_episode.scanned_episode,
                    "url": result["url"],
                })

                # Send notification
                self.notification_service.notify_episode_posted(
                    show_title=eligible_episode.show_title,
                    episode=str(eligible_episode.scanned_episode),
                    url=result["url"],
                    is_automated=True,
                    show_title_en=show.title_en or None,
                    sources=eligible_episode.sources,
                )

            except Exception as e:
                failed.append({
                    "show_id": eligible_episode.show_id,
                    "show_title": eligible_episode.show_title,
                    "episode": eligible_episode.scanned_episode,
                    "error": str(e),
                })

        return AutoPostResult(posted=posted, skipped=skipped, failed=failed)

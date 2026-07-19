"""Service for running scheduled scans and auto-posting episodes."""
import logging

from django.utils import timezone

from .scan_result import ScanResult

logger = logging.getLogger(__name__)


def _make_aware(dt):
    """Convert naive datetime to timezone-aware."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


class SchedulerService:
    """Service for running scheduled scans with auto-post functionality."""

    def __init__(self):
        self._scanner = None
        self._nekobt_scanner = None
        self._auto_post_service = None

    @property
    def scanner(self):
        """Lazy-load NyaaScanner to avoid requiring feedparser at import time."""
        if self._scanner is None:
            from .nyaa_scanner import NyaaScanner
            self._scanner = NyaaScanner()
        return self._scanner

    @property
    def nekobt_scanner(self):
        """Lazy-load NekobtScanner to avoid requiring feedparser at import time."""
        if self._nekobt_scanner is None:
            from .nekobt_scanner import NekobtScanner
            self._nekobt_scanner = NekobtScanner()
        return self._nekobt_scanner

    def _scan_all_sources(self, enabled_shows):
        """Run every wired-in scanner against enabled_shows and merge into one ScanResult."""
        nyaa_result = self.scanner.scan_recent(enabled_shows)
        nekobt_result = self.nekobt_scanner.scan_recent(enabled_shows)
        return ScanResult(
            scan_time=nyaa_result.scan_time,
            episodes_found=nyaa_result.episodes_found + nekobt_result.episodes_found,
            shows_scanned=nyaa_result.shows_scanned,
            errors=nyaa_result.errors + nekobt_result.errors,
        )

    def _store_scan_episodes(self, scan_history, scan_result):
        """
        Create one ScanEpisode row per (show, episode) found in scan_result.

        When multiple scanners find the same episode, their sources are merged
        into a single comma-separated `source` value on one row, rather than
        creating a separate row per scanner.
        """
        from ..models import ScanEpisode

        for (show_id, episode_number), group in scan_result.group_by_episode().items():
            sources = sorted(set(found.source for found in group))
            representative = group[0]
            ScanEpisode.objects.create(
                scan=scan_history,
                show_id=show_id,
                episode_number=str(episode_number),
                source=", ".join(sources),
                source_title=representative.source_title,
                link=representative.link,
                found_at=_make_aware(min(found.found_at for found in group)),
                status="found"
            )

    @property
    def auto_post_service(self):
        """Lazy-load AutoPostService to avoid requiring praw at import time."""
        if self._auto_post_service is None:
            from .auto_post_service import AutoPostService
            self._auto_post_service = AutoPostService()
        return self._auto_post_service

    def run_scheduled_scan(self):
        """
        Run a scheduled scan for new episodes.

        Steps:
        1. Check if scheduler is enabled via SchedulerConfig
        2. Create ScanHistory record
        3. Run NyaaScanner and NekobtScanner scan_recent(), merged into one ScanResult
        4. Store found episodes as ScanEpisode records
        5. Run AutoPostService to determine eligibility and post
        6. Update ScanEpisode statuses and ScanHistory counts
        7. Update SchedulerConfig.last_run
        """
        from ..models import SchedulerConfig, ScanHistory, ScanEpisode, Show

        # 1. Check if scheduler is enabled
        config = SchedulerConfig.get_config()
        if not config.enabled:
            logger.info("Scheduler is disabled, skipping scan")
            return None

        logger.info("Starting scheduled scan...")

        # 2. Create ScanHistory record
        scan_history = ScanHistory.objects.create(
            trigger_type="scheduled",
            completed=False
        )

        try:
            # 3. Get enabled shows and run scan
            enabled_shows = Show.objects.filter(enabled=True)
            shows_count = enabled_shows.count()

            if shows_count == 0:
                logger.info("No enabled shows found, skipping scan")
                scan_history.shows_scanned = 0
                scan_history.completed = True
                scan_history.save()
                config.last_run = timezone.now()
                config.save()
                return scan_history

            scan_result = self._scan_all_sources(enabled_shows)

            # Update scan history with basic stats
            scan_history.shows_scanned = scan_result.shows_scanned
            scan_history.episodes_found = len(scan_result.episodes_found)
            scan_history.errors = scan_result.errors
            scan_history.save()

            # 4. Store found episodes as ScanEpisode records
            self._store_scan_episodes(scan_history, scan_result)

            # 5. Determine eligibility
            eligibilities = self.auto_post_service.determine_eligibility(scan_result)

            # Update ScanEpisode status based on eligibility
            for elig in eligibilities:
                scan_episode = ScanEpisode.objects.filter(
                    scan=scan_history,
                    show_id=elig.show_id,
                    episode_number=str(elig.scanned_episode),
                ).first()

                if scan_episode:
                    if elig.is_eligible:
                        scan_episode.status = "eligible"
                        scan_episode.status_reason = elig.reason
                    else:
                        scan_episode.status = "skipped"
                        scan_episode.status_reason = elig.reason
                    scan_episode.save()

            # 6. Post eligible episodes
            post_result = self.auto_post_service.post_eligible_episodes(eligibilities)

            # Update ScanEpisode records with post results
            for posted in post_result.posted:
                scan_episode = ScanEpisode.objects.filter(
                    scan=scan_history,
                    show_id=posted["show_id"],
                    episode_number=str(posted["episode"]),
                ).first()
                if scan_episode:
                    scan_episode.status = "posted"
                    scan_episode.discussion_url = posted["url"]
                    scan_episode.save()

            for failed in post_result.failed:
                scan_episode = ScanEpisode.objects.filter(
                    scan=scan_history,
                    show_id=failed["show_id"],
                    episode_number=str(failed["episode"]),
                ).first()
                if scan_episode:
                    scan_episode.status = "failed"
                    scan_episode.status_reason = failed["error"]
                    scan_episode.save()

            # Update scan history counts
            scan_history.episodes_posted = len(post_result.posted)
            scan_history.episodes_skipped = len(post_result.skipped)
            scan_history.episodes_failed = len(post_result.failed)
            scan_history.completed = True
            scan_history.save()

            # 7. Update last run time
            config.last_run = timezone.now()
            config.save()

            logger.info(
                f"Scheduled scan completed: {scan_history.episodes_found} found, "
                f"{scan_history.episodes_posted} posted, "
                f"{scan_history.episodes_skipped} skipped, "
                f"{scan_history.episodes_failed} failed"
            )

            return scan_history

        except Exception as e:
            logger.exception("Error during scheduled scan")
            scan_history.errors = scan_history.errors + [str(e)]
            scan_history.completed = True
            scan_history.save()

            # Still update last run time so we don't retry immediately
            config.last_run = timezone.now()
            config.save()

            raise

    def run_manual_scan(self):
        """
        Run a manual scan (called from views) and store results in DB.

        Similar to run_scheduled_scan but with trigger_type="manual".
        """
        from ..models import ScanHistory, Show

        logger.info("Starting manual scan...")

        # Create ScanHistory record
        scan_history = ScanHistory.objects.create(
            trigger_type="manual",
            completed=False
        )

        try:
            # Get enabled shows and run scan
            enabled_shows = Show.objects.filter(enabled=True)
            shows_count = enabled_shows.count()

            if shows_count == 0:
                logger.info("No enabled shows found")
                scan_history.shows_scanned = 0
                scan_history.completed = True
                scan_history.save()
                return scan_history

            scan_result = self._scan_all_sources(enabled_shows)

            # Update scan history with basic stats
            scan_history.shows_scanned = scan_result.shows_scanned
            scan_history.episodes_found = len(scan_result.episodes_found)
            scan_history.errors = scan_result.errors
            scan_history.completed = True
            scan_history.save()

            # Store found episodes as ScanEpisode records
            self._store_scan_episodes(scan_history, scan_result)

            logger.info(
                f"Manual scan completed: {scan_history.episodes_found} found "
                f"across {scan_history.shows_scanned} shows"
            )

            return scan_history

        except Exception as e:
            logger.exception("Error during manual scan")
            scan_history.errors = scan_history.errors + [str(e)]
            scan_history.completed = True
            scan_history.save()
            raise

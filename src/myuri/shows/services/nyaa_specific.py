import logging
import re
from datetime import datetime
from urllib.parse import quote as url_quote

from .nyaa_scanner import NyaaScanner
from .scan_result import FoundEpisode, ScanResult

logger = logging.getLogger(__name__)


class NyaaSpecificScanner(NyaaScanner):
    """
    Searches Nyaa.si for a specific show by title query rather than
    scanning the general recent-releases feed.

    Compared to NyaaScanner.scan_recent (which fetches everything and
    filters locally), this class issues a targeted search request per
    show so results are already narrowed by Nyaa before any local
    filtering occurs.
    """

    _search_url = "https://{domain}/?page=rss&c=1_2&f={filter}&q={q}"

    def scan_show(self, show, max_age_days: int = 2) -> ScanResult:
        """
        Search Nyaa specifically for one show and return matching episodes.

        Args:
            show: A Show model instance (must have .title; .title_en and
                  .aliases are also used when verifying results).
            max_age_days: Only consider torrents published within this
                          many days.

        Returns:
            ScanResult with found episodes (shows_scanned is always 1).
        """
        result = ScanResult(scan_time=datetime.now(), shows_scanned=1)

        query = self._build_query(show.title)
        logger.info("Searching Nyaa specifically for: %s (query=%s)", show.title, query)

        try:
            torrents = self._fetch_show_torrents(query)
        except Exception as e:
            logger.exception("Failed to fetch Nyaa search feed for %s", show.title)
            result.errors.append(f"Failed to fetch RSS feed: {e}")
            return result

        for torrent in torrents:
            if not self._is_recent(torrent, max_age_days):
                continue

            title = torrent.get("title", "")

            if self._is_excluded(title):
                continue

            episode_num = self._extract_episode_number(title)
            if episode_num is None or episode_num <= 0:
                continue

            # Even though Nyaa has already filtered by query, verify the
            # torrent actually belongs to this show (guards against broad
            # search matches and avoids false positives from aliases).
            if not self._matches_show(torrent, show):
                continue

            result.episodes_found.append(FoundEpisode(
                show_id=show.id,
                show_title=show.title,
                episode_number=episode_num,
                source="Nyaa",
                torrent_title=title,
                found_at=self._parse_torrent_date(torrent),
                link=torrent.get("id", torrent.get("link", "")),
            ))

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_query(self, show_title: str) -> str:
        """
        Sanitize a show title into a URL-encoded Nyaa search query.

        Follows the same cleaning rules as the legacy feed scanner:
        - Strip punctuation that confuses Nyaa's parser
        - Drop the word "season" (Nyaa indexes by cour, not season label)
        - Collapse runs of whitespace
        - Preserve leading "-" tokens so callers can use the Nyaa NOT operator
        """
        query = re.sub(r"[`~!@#$%^&*()+=:;,.<>?/|\"]+", " ", show_title)
        query = re.sub(r"season", " ", query, flags=re.I)
        query = re.sub(r" +", " ", query)
        query = re.sub(r"(?<=[^ ])-", " ", query)  # only strip mid-word hyphens
        return url_quote(query.strip(), safe="", errors="ignore")

    def _fetch_show_torrents(self, query: str) -> list:
        """Fetch the Nyaa search RSS feed for an already-encoded query string."""
        try:
            import feedparser
        except ImportError:
            raise ImportError(
                "feedparser is required for scanning. "
                "Install it with: pip install feedparser"
            )

        url = self._search_url.format(
            domain=self.domain,
            filter=self.quality_filter,
            q=query,
        )

        feed = feedparser.parse(url)

        if feed.bozo:
            logger.warning("RSS feed may be malformed for query: %s", query)

        return feed.get("entries", [])

    def _matches_show(self, torrent: dict, show) -> bool:
        """
        Return True if the torrent title contains words from any of the
        show's known names (title, English title, or aliases).

        Reuses the word-subset matching already defined on the parent so
        behaviour stays consistent across both scanner types.
        """
        return bool(self._find_matching_shows(torrent, [show]))

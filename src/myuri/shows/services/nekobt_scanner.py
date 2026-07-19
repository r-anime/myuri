import logging
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

from .scan_result import FoundEpisode, ScanResult

logger = logging.getLogger(__name__)


class NekobtScanner:
    """Scanner for finding anime episode releases on nekobt.to (torznab API)."""

    # fansub_lang/sub_lang restrict results to English-subbed releases; uploader_id
    # scopes the feed to a single trusted uploader account.
    _recent_url = (
        "https://nekobt.to/api/torznab/api"
        "?t=search&fansub_lang=en&sub_lang=en&uploader_id=7251460167698"
    )

    def scan_recent(self, shows, max_age_days: int = 2) -> ScanResult:
        """
        Scan recent nekobt.to torrents for episodes matching the given shows.

        Args:
            shows: QuerySet or list of Show model instances
            max_age_days: Only consider torrents published within this many days

        Returns:
            ScanResult with found episodes
        """
        result = ScanResult(
            scan_time=datetime.now(),
            shows_scanned=len(shows) if hasattr(shows, '__len__') else shows.count(),
        )

        try:
            torrents = self._fetch_recent_torrents()
        except Exception as e:
            logger.exception("Failed to fetch nekobt.to torznab feed")
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

            matching_shows = self._find_matching_shows(torrent, shows)

            for show in matching_shows:
                result.episodes_found.append(FoundEpisode(
                    show_id=show.id,
                    show_title=show.title,
                    episode_number=episode_num,
                    source="Nekobt",
                    source_title=title,
                    found_at=self._parse_torrent_date(torrent),
                    link=torrent.get("id", torrent.get("link", "")),
                ))

        return result

    def _fetch_recent_torrents(self) -> list:
        """Fetch recent torrents from the nekobt.to torznab feed."""
        try:
            import feedparser
        except ImportError:
            raise ImportError(
                "feedparser is required for scanning. "
                "Install it with: pip install feedparser"
            )

        feed = feedparser.parse(self._recent_url)

        if feed.bozo:
            logger.warning("RSS feed may be malformed")

        return feed.get("entries", [])

    def _is_recent(self, torrent: dict, max_age_days: int) -> bool:
        """Check if torrent was published within max_age_days."""
        published = torrent.get("published_parsed")
        if not published:
            return False

        episode_date = datetime(*published[:6])
        date_diff = datetime.utcnow() - episode_date
        return date_diff < timedelta(days=max_age_days)

    def _parse_torrent_date(self, torrent: dict) -> datetime:
        """Parse torrent publication date."""
        published = torrent.get("published_parsed")
        if published:
            return datetime(*published[:6])
        return datetime.utcnow()

    def _is_excluded(self, title: str) -> bool:
        """Check if torrent title matches exclusion patterns."""
        return any(ex.search(title) is not None for ex in self._excludors)

    def _find_matching_shows(self, torrent: dict, shows) -> list:
        """Find shows that match the torrent title."""
        found_shows = []
        title = torrent.get("title", "")
        title_word_sets = [set(v.split()) for v in self._normalize_name_variants(title)]

        for show in shows:
            names = [show.title]
            if show.title_en:
                names.append(show.title_en)
            if show.aliases:
                names.extend(show.aliases.strip().split("\n"))

            for name in names:
                if not name.strip():
                    continue

                show_word_sets = [set(v.split()) for v in self._normalize_name_variants(name)]
                if any(
                    show_words and show_words.issubset(title_words)
                    for show_words in show_word_sets
                    for title_words in title_word_sets
                ):
                    found_shows.append(show)
                    break

        return found_shows

    # Patterns to exclude (batch releases, dubs, BDs, etc.)
    _excludors = [re.compile(x, re.I) for x in [
        r"\b(batch|vol(ume|\.)? ?\d+|dub|dubbed)\b",
        r"\b(bd(?:remux|rip)?|bluray)\b",
    ]]

    # nekobt titles are consistently "[Group] Show Name SxxEyy <quality tags>",
    # so a single SxxEyy pattern covers the format (unlike Nyaa's chaotic naming).
    _num_extractor = re.compile(r"\bS\d+E(\d+)\b", re.I)

    def _extract_episode_number(self, title: str) -> Optional[int]:
        """Extract episode number from torrent title."""
        match = self._num_extractor.search(title)
        if match is not None:
            return int(match.group(1))
        return None

    def _normalize_name(self, name: str) -> str:
        """
        Normalize a title for string comparison.
        Converts to lowercase, removes special characters, and strips season info.
        """
        name = name.casefold()
        name = re.sub("[^a-z0-9]", " ", name)
        name = re.sub("_", " ", name)
        name = re.sub("season \\d( part \\d)?", " ", name)
        name = re.sub("\\s+", " ", name)
        return name.strip()

    def _strip_accents(self, name: str) -> str:
        """Fold accented/diacritic characters to their base ASCII letter (e.g. 'é' -> 'e')."""
        decomposed = unicodedata.normalize("NFKD", name)
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    def _normalize_name_variants(self, name: str) -> list:
        """Return normalized forms of a name: as-is, and with accents folded to ASCII."""
        variants = [self._normalize_name(name)]
        ascii_variant = self._normalize_name(self._strip_accents(name))
        if ascii_variant not in variants:
            variants.append(ascii_variant)
        return variants

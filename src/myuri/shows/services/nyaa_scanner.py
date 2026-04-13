import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from .scan_result import FoundEpisode, ScanResult

logger = logging.getLogger(__name__)


class NyaaScanner:
    """Scanner for finding anime episode releases on Nyaa.si."""

    # c=1_2 restricts the feed to English-translated anime only (raws and non-English subs are excluded).
    # f=2, the RSS feed only returns torrents from uploaders with Nyaa's "trusted" badge. Fansub groups and others without that badge are completely excluded.
    _recent_url = "https://{domain}/?page=rss&c=1_2&f={filter}"

    def __init__(self, domain: str = "nyaa.si", quality_filter: str = "2"):
        self.domain = domain
        self.quality_filter = quality_filter

    def scan_recent(self, shows, max_age_days: int = 2) -> ScanResult:
        """
        Scan recent Nyaa torrents for episodes matching the given shows.

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
            logger.exception("Failed to fetch Nyaa RSS feed")
            result.errors.append(f"Failed to fetch RSS feed: {e}")
            return result

        for torrent in torrents:
            # Skip if too old
            if not self._is_recent(torrent, max_age_days):
                continue

            # Skip if excluded (batch, BD, etc.)
            title = torrent.get("title", "")
            if self._is_excluded(title):
                continue

            # Extract episode number
            episode_num = self._extract_episode_number(title)
            if episode_num is None or episode_num <= 0:
                continue

            # Find matching shows
            matching_shows = self._find_matching_shows(torrent, shows)

            for show in matching_shows:
                found_episode = FoundEpisode(
                    show_id=show.id,
                    show_title=show.title,
                    episode_number=episode_num,
                    source="Nyaa",
                    torrent_title=title,
                    found_at=self._parse_torrent_date(torrent),
                    link=torrent.get("id", torrent.get("link", "")),
                )
                result.episodes_found.append(found_episode)

        return result

    def _fetch_recent_torrents(self) -> list:
        """Fetch recent torrents from Nyaa RSS feed."""
        try:
            import feedparser
        except ImportError:
            raise ImportError(
                "feedparser is required for scanning. "
                "Install it with: pip install feedparser"
            )

        url = self._recent_url.format(
            domain=self.domain,
            filter=self.quality_filter,
        )

        feed = feedparser.parse(url)

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
        normalized_title = self._normalize_name(title)
        title_words = set(normalized_title.split())

        for show in shows:
            # Collect all possible names for the show
            names = [show.title]
            if show.title_en:
                names.append(show.title_en)
            if show.aliases:
                names.extend(show.aliases.strip().split("\n"))

            for name in names:
                if not name.strip():
                    continue

                # Match if all words in show name are in torrent title
                show_words = set(self._normalize_name(name).split())
                if show_words and show_words.issubset(title_words):
                    found_shows.append(show)
                    break

        return found_shows

    # Patterns to exclude (batch releases, dubs, BDs, etc.)
    _excludors = [re.compile(x, re.I) for x in [
        r"\.srt$",
        r"\b(batch|vol(ume|\.)? ?\d+|dub|dubbed)\b",
        r"\b(bd(?:remux|rip)?|bluray)\b",
        r"PV.?\d+",
        r"pre-?air",
    ]]

    # Patterns to extract episode numbers
    _num_extractors = [re.compile(x, re.I) for x in [
        # " - " separator between show and episode
        r"\[(?:horriblesubs|SubsPlease|commie|hiryuu|kuusou|fff|merchant|lolisubs|hitoku|erai-raws|davinci|asenshi|mezashite|anonyneko|pas|ryuujitk|rip time)\] .+ - (\d+) ",
        r"\[DameDesuYo\] .+ - (\d+)[ v]",
        r"\[Some-Stuffs\] .+ (\d{3}) ",
        r"\[(?:orz|hayaku|sxrp|Weeaboo-Shogun)\] .+ (\d+)", # No separator
        r"\[(?:kaitou|gg)\]_.+_-_(\d+)_", # "_-_" separator
        r"\[flysubs].+ - (\d+)\[.+\]", # "_-_" separator
        r".+_(\d+)\[(?:please_sub_this_viz)\]", # "_-_" separator
        r"\[doremi\]\..+\.(\d+)", # "." separator
        r"\[anon\] .+? (\d{2,})",
        r"\[seiya\] .+ - (\d+) \[.+\]",
        r"\[U3-Web\] .+ \[EP(\d+)\]",
        r"\[ember\] .+ s(?:\d+)e(\d+)",
        r".+ (\d+) \[(?:Anon-kun Wa Sugoi)\]",  # Group after title, spaces
        r"(?:.+).S(?:\d+)E(\d+).Laelaps.Calling.(?:\d+)p.(?:.+)",
        r"\[(?:SenritsuSubs|AtlasSubbed|Rakushun)\] .+ - (\d+)",
        #r".+ - S(?:\d+)E(\d+) ", # using the S01E12 format
        r".+\Ws(?:eason)?[\s.]?\d+[\s.]?e(?:pisode)?[\s.]?(\d+)", # SxxEyy format (allow s/season, e/episode, ./space separation
        r"\[.*?\][ _][^\(\[]+[ _](?:-[ _])?(\d+)[ _]", # Generic to make a best guess. Does not include . separation due to the common "XXX vol.01" format
        r".*?[ _](\d+)[ _]\[\d+p\]", # No tag followed by quality
        r".*?episode[ _](\d+)", # Completely unformatted, but with the "Episode XX" text
        r".*[ _]-[ _](\d+)(?:[ _].*)?$", # - separator
        r".*(\d+)\.mkv$", # num right before extension
    ]]

    def _extract_episode_number(self, title: str) -> Optional[int]:
        """Extract episode number from torrent title."""
        for regex in self._num_extractors:
            match = regex.match(title)
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

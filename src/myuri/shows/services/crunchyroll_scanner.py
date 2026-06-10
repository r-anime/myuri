import base64
import logging
import re
from datetime import datetime
from typing import Optional

import requests

from .scan_result import FoundEpisode, ScanResult

logger = logging.getLogger(__name__)

_CR_AUTH_URL   = "https://www.crunchyroll.com/auth/v1/token"
_CR_SERIES_URL = "https://www.crunchyroll.com/content/v2/cms/series/{slug}/seasons"
_CR_SEASON_URL = "https://www.crunchyroll.com/content/v2/cms/seasons/{season_id}/episodes"
# Public web client — no secret. Reproducible: base64.b64encode(b"cr_web:").decode()
_CR_AUTH_HEADER = "Basic " + base64.b64encode(b"cr_web:").decode()
_CR_USER_AGENT = "HoloUserAgent episode discussion bot (run by /u/badspler, see https://github.com/r-anime/holo)"

# Matches new-style Crunchyroll series URLs: crunchyroll.com/series/GG5H5XQ0D
_SERIES_ID_RE = re.compile(r"crunchyroll\.com/series/([A-Z0-9]+)", re.I)


class CrunchyrollScanner:
    """Scanner for finding anime episode releases on Crunchyroll."""

    def scan_recent(self, shows) -> ScanResult:
        """Scan Crunchyroll for episodes matching the given shows.

        Only shows with a ShowLink of link_type.slug == "crunchyroll" pointing to
        a new-style series URL (crunchyroll.com/series/<ID>) are scanned.

        Args:
            shows: QuerySet or list of Show model instances

        Returns:
            ScanResult with found episodes
        """
        result = ScanResult(scan_time=datetime.now(), shows_scanned=0)

        try:
            token = self._get_bearer_token()
        except Exception as e:
            logger.exception("Crunchyroll authentication failed")
            result.errors.append(f"Crunchyroll auth failed: {e}")
            return result

        headers = {
            "Authorization": "Bearer " + token,
            "User-Agent": _CR_USER_AGENT,
        }

        for show in shows:
            slug = self._get_cr_slug(show)
            if slug is None:
                continue

            result.shows_scanned += 1

            try:
                episodes = self._fetch_episodes_for_show(slug, headers)
            except Exception as e:
                logger.exception(f"Failed to fetch Crunchyroll episodes for {show.title!r}")
                result.errors.append(f"{show.title}: {e}")
                continue

            for episode in episodes:
                if self._is_clip(episode):
                    continue
                episode_num = self._extract_episode_number(episode)
                if episode_num is None or episode_num <= 0:
                    continue
                result.episodes_found.append(FoundEpisode(
                    show_id=show.id,
                    show_title=show.title,
                    episode_number=episode_num,
                    source="Crunchyroll",
                    source_title=episode.get("title", ""),
                    found_at=self._parse_episode_date(episode) or datetime.utcnow(),
                    link=f"https://www.crunchyroll.com/watch/{episode['id']}",
                ))

        return result

    def _get_bearer_token(self) -> str:
        """Authenticate anonymously and return a Bearer access token."""
        r = requests.post(
            _CR_AUTH_URL,
            headers={
                "Authorization": _CR_AUTH_HEADER,
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": _CR_USER_AGENT,
            },
            data={"grant_type": "client_id"},
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def _get_cr_slug(self, show) -> Optional[str]:
        """Return the Crunchyroll series ID for a show, or None if not configured."""
        for link in show.links.select_related("link_type").all():
            if link.link_type.slug == "crunchyroll":
                m = _SERIES_ID_RE.search(link.url)
                if m:
                    return m.group(1)
                logger.warning(
                    f"Show {show.title!r} has a Crunchyroll link but the URL "
                    f"does not match the expected series ID format: {link.url!r}"
                )
                return None
        return None

    def _fetch_episodes_for_show(self, slug: str, headers: dict) -> list:
        """Fetch the episode list for the latest season of a series.

        This is the mock boundary for tests.
        """
        seasons_r = requests.get(_CR_SERIES_URL.format(slug=slug), headers=headers)
        seasons_r.raise_for_status()
        seasons = seasons_r.json().get("data", [])
        if not seasons:
            return []

        season_id = seasons[-1]["id"]
        episodes_r = requests.get(_CR_SEASON_URL.format(season_id=season_id), headers=headers)
        episodes_r.raise_for_status()
        return episodes_r.json().get("data", [])

    def _parse_episode_date(self, episode: dict) -> Optional[datetime]:
        """Parse the episode air date into a naive UTC datetime."""
        date_str = episode.get("episode_air_date")
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None

    def _is_clip(self, episode: dict) -> bool:
        return bool(episode.get("is_clip", False))

    def _extract_episode_number(self, episode: dict) -> Optional[int]:
        """Extract an integer episode number from the episode dict."""
        num = episode.get("episode_number")
        if isinstance(num, int) and num >= 0:
            return num
        # Fall back to the string 'episode' field for fractional/OVA-style values
        raw = str(episode.get("episode", ""))
        m = re.match(r"(\d+)[abc]?", raw)
        return int(m.group(1)) if m else None

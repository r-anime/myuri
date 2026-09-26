import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from .scan_result import FoundEpisode, ScanResult

logger = logging.getLogger(__name__)

_YT_PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_YT_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
_YT_PAGE_SIZE = 50  # API maximum for both maxResults and ids-per-request

# Matches playlist URLs: youtube.com/playlist?list=PLxxxx
_PLAYLIST_ID_RE = re.compile(r"youtube\.com/playlist\?list=([\w-]+)", re.I)

# Titles matching any of these are promos/extras, not episodes. PV/OP/ED are
# case-sensitive so ordinary words ("Ed", "op") in episode titles don't match.
_EXCLUDERS = [
    re.compile(r"(?:[^a-zA-Z]|^)(?:PV|OP|ED)(?:[^a-zA-Z]|$)"),
    re.compile(r"blu.?ray", re.I),
    re.compile(r"preview", re.I),
    re.compile(r"trailer", re.I),
]

# Tried in order: explicit markers first, generic 2-3 digit number last.
_NUM_EXTRACTORS = [
    re.compile(r"S\d+\s*E(\d+)", re.I),
    re.compile(r"episode\s*(\d+)", re.I),
    re.compile(r"\bep\.?\s*(\d+)", re.I),
    re.compile(r"第\s*(\d+)\s*[話话集回]"),
    re.compile(r"#\s*(\d+)"),
    re.compile(r".*\D(\d{2,3})(?:\D|$)"),
]

_MAX_EPISODE = 720


class YoutubeScanner:
    """Scanner for finding anime episode releases in YouTube playlists."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    @property
    def api_key(self) -> Optional[str]:
        """Lazy-load the YouTube Data API key from config.ini."""
        if self._api_key is None:
            from .config_loader import load_youtube_api_key
            self._api_key = load_youtube_api_key() or ""
        return self._api_key or None

    def scan_recent(self, shows, max_age_days: int = 2) -> ScanResult:
        """
        Scan YouTube playlists for recent episodes matching the given shows.

        Only shows with a ShowLink of link_type.slug == "youtube" pointing to a
        playlist URL (youtube.com/playlist?list=<ID>) are scanned.

        Args:
            shows: QuerySet or list of Show model instances
            max_age_days: Only include videos published within this many days

        Returns:
            ScanResult with found episodes
        """
        result = ScanResult(scan_time=datetime.now(), shows_scanned=0)

        targets = []
        for show in shows:
            playlist_id = self._get_playlist_id(show)
            if playlist_id is not None:
                targets.append((show, playlist_id))

        if not targets:
            return result

        api_key = self.api_key
        if not api_key:
            logger.warning("YouTube API key not configured, skipping YouTube scan")
            result.errors.append("YouTube API key not configured")
            return result

        for show, playlist_id in targets:
            result.shows_scanned += 1

            try:
                videos = self._fetch_videos_for_playlist(playlist_id, api_key)
            except Exception as e:
                logger.exception(f"Failed to fetch YouTube playlist for {show.title!r}")
                result.errors.append(f"{show.title}: {e}")
                continue

            for video in videos:
                if not self._is_valid_video(video):
                    continue
                published = self._parse_published_date(video)
                if published is None or datetime.utcnow() - published >= timedelta(days=max_age_days):
                    continue
                title = video["snippet"].get("title", "")
                episode_num = self._extract_episode_number(title)
                if episode_num is None:
                    continue
                result.episodes_found.append(FoundEpisode(
                    show_id=show.id,
                    show_title=show.title,
                    episode_number=episode_num,
                    source="YouTube",
                    source_title=title,
                    found_at=published,
                    link=_YT_WATCH_URL.format(video_id=video["id"]),
                ))

        return result

    def _get_playlist_id(self, show) -> Optional[str]:
        """Return the YouTube playlist ID for a show, or None if not configured."""
        for link in show.links.select_related("link_type").all():
            if link.link_type.slug == "youtube":
                m = _PLAYLIST_ID_RE.search(link.url)
                if m:
                    return m.group(1)
                logger.warning(
                    f"Show {show.title!r} has a YouTube link but the URL "
                    f"is not a playlist URL: {link.url!r}"
                )
                return None
        return None

    def _fetch_videos_for_playlist(self, playlist_id: str, api_key: str) -> list:
        """Fetch video details (status + snippet) for every item in a playlist.

        This is the mock boundary for tests.
        """
        video_ids = []
        page_token = None
        while True:
            params = {
                "part": "contentDetails",
                "maxResults": _YT_PAGE_SIZE,
                "playlistId": playlist_id,
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            r = requests.get(_YT_PLAYLIST_ITEMS_URL, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        videos = []
        for i in range(0, len(video_ids), _YT_PAGE_SIZE):
            r = requests.get(
                _YT_VIDEOS_URL,
                params={
                    "part": "status,snippet",
                    "id": ",".join(video_ids[i:i + _YT_PAGE_SIZE]),
                    "key": api_key,
                },
                timeout=10,
            )
            r.raise_for_status()
            videos.extend(r.json().get("items", []))
        return videos

    def _is_valid_video(self, video: dict) -> bool:
        """Return True if the video is public/unlisted, already live, and not an extra."""
        if video.get("status", {}).get("privacyStatus") == "private":
            return False
        snippet = video.get("snippet", {})
        if snippet.get("liveBroadcastContent") == "upcoming":
            return False
        title = snippet.get("title", "")
        if not title:
            return False
        if any(ex.search(title) for ex in _EXCLUDERS):
            return False
        return True

    def _parse_published_date(self, video: dict) -> Optional[datetime]:
        """Parse snippet.publishedAt into a naive UTC datetime."""
        date_str = video.get("snippet", {}).get("publishedAt")
        if not date_str:
            return None
        try:
            parsed = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def _extract_episode_number(self, title: str) -> Optional[int]:
        """Extract an episode number from a video title, or None if not found."""
        for regex in _NUM_EXTRACTORS:
            m = regex.search(title)
            if m:
                num = int(m.group(1))
                return num if 0 < num < _MAX_EPISODE else None
        return None

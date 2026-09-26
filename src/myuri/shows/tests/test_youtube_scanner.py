from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from shows.models import LinkType, Season, Show, ShowLink
from shows.services.youtube_scanner import YoutubeScanner

_PLAYLIST_ID = "PLgLoNaiAnCSf0ArHXvdfEja_wTedZaTQr"


def _make_video(title, video_id="vid00001", days_ago=0, privacy="public", live="none"):
    """Build a minimal video dict matching the YouTube videos API response shape."""
    published = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return {
        "id": video_id,
        "status": {"privacyStatus": privacy},
        "snippet": {
            "title": title,
            "publishedAt": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "liveBroadcastContent": live,
        },
    }


class YoutubeScannerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.yt_link_type = LinkType.objects.create(
            name="YouTube", slug="youtube", category="stream"
        )

    def _make_show(self, **kwargs):
        defaults = dict(title="Test Show", title_en="", aliases="", has_source=False, season=self.season)
        defaults.update(kwargs)
        return Show.objects.create(**defaults)

    def _add_yt_link(self, show, playlist_id=_PLAYLIST_ID, url=None):
        ShowLink.objects.create(
            show=show,
            link_type=self.yt_link_type,
            url=url or f"https://www.youtube.com/playlist?list={playlist_id}",
        )

    def _scan(self, shows, videos_by_playlist, **kwargs):
        """Run scan_recent with _fetch_videos_for_playlist mocked."""
        scanner = YoutubeScanner(api_key="fake_key")

        def fake_fetch(playlist_id, api_key):
            return videos_by_playlist.get(playlist_id, [])

        with patch.object(scanner, "_fetch_videos_for_playlist", side_effect=fake_fetch):
            return scanner.scan_recent(shows, **kwargs)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_scan_recent_finds_episode(self):
        """scan_recent returns a FoundEpisode for a show with a YouTube playlist link."""
        show = self._make_show()
        self._add_yt_link(show)

        result = self._scan([show], {_PLAYLIST_ID: [_make_video("Test Show Episode 5", video_id="abc123")]})

        self.assertEqual(len(result.episodes_found), 1)
        ep = result.episodes_found[0]
        self.assertEqual(ep.show_id, show.id)
        self.assertEqual(ep.episode_number, 5)
        self.assertEqual(ep.source, "YouTube")
        self.assertEqual(ep.source_title, "Test Show Episode 5")
        self.assertEqual(ep.link, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(result.errors, [])

    def test_scan_recent_shows_scanned_counts_youtube_shows(self):
        """shows_scanned reflects only shows that have a YouTube playlist link."""
        show_with = self._make_show(title="Show A")
        show_without = self._make_show(title="Show B")
        self._add_yt_link(show_with)

        result = self._scan([show_with, show_without], {})

        self.assertEqual(result.shows_scanned, 1)

    # ------------------------------------------------------------------
    # Link handling
    # ------------------------------------------------------------------

    def test_scan_recent_skips_show_without_youtube_link(self):
        """Shows with no YouTube ShowLink are skipped without fetching."""
        show = self._make_show()
        scanner = YoutubeScanner(api_key="fake_key")

        with patch.object(scanner, "_fetch_videos_for_playlist") as mock_fetch:
            result = scanner.scan_recent([show])

        mock_fetch.assert_not_called()
        self.assertEqual(result.episodes_found, [])
        self.assertEqual(result.errors, [])

    def test_scan_recent_skips_non_playlist_youtube_link(self):
        """A YouTube link that is a channel/video URL rather than a playlist is skipped."""
        show = self._make_show()
        self._add_yt_link(show, url="https://www.youtube.com/@MuseAsia")
        scanner = YoutubeScanner(api_key="fake_key")

        with patch.object(scanner, "_fetch_videos_for_playlist") as mock_fetch:
            result = scanner.scan_recent([show])

        mock_fetch.assert_not_called()
        self.assertEqual(result.shows_scanned, 0)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _assert_filtered(self, video):
        show = self._make_show()
        self._add_yt_link(show)
        result = self._scan([show], {_PLAYLIST_ID: [video]})
        self.assertEqual(result.episodes_found, [])

    def test_scan_recent_filters_old_videos(self):
        self._assert_filtered(_make_video("Episode 1", days_ago=3))

    def test_scan_recent_filters_private_videos(self):
        self._assert_filtered(_make_video("Episode 1", privacy="private"))

    def test_scan_recent_filters_upcoming_videos(self):
        self._assert_filtered(_make_video("Episode 1", live="upcoming"))

    def test_scan_recent_filters_pv(self):
        self._assert_filtered(_make_video("Test Show PV 2"))

    def test_scan_recent_filters_ending(self):
        self._assert_filtered(_make_video("Test Show Non-credit ED 01"))

    def test_scan_recent_filters_preview(self):
        self._assert_filtered(_make_video("Episode 3 Preview"))

    def test_scan_recent_filters_video_without_episode_number(self):
        self._assert_filtered(_make_video("Test Show special message from the cast"))

    def test_scan_recent_respects_max_age_days(self):
        """max_age_days widens the window (used by per-show scans)."""
        show = self._make_show()
        self._add_yt_link(show)

        result = self._scan([show], {_PLAYLIST_ID: [_make_video("Episode 2", days_ago=5)]}, max_age_days=7)

        self.assertEqual(len(result.episodes_found), 1)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_scan_recent_fetch_error_is_recorded(self):
        """A fetch failure for one show is recorded in errors and scanning continues."""
        show_bad = self._make_show(title="Bad Show")
        show_good = self._make_show(title="Good Show")
        self._add_yt_link(show_bad, playlist_id="PLbad")
        self._add_yt_link(show_good, playlist_id="PLgood")
        scanner = YoutubeScanner(api_key="fake_key")

        def fake_fetch(playlist_id, api_key):
            if playlist_id == "PLbad":
                raise ConnectionError("timeout")
            return [_make_video("Episode 3")]

        with patch.object(scanner, "_fetch_videos_for_playlist", side_effect=fake_fetch):
            result = scanner.scan_recent([show_bad, show_good])

        self.assertEqual(len(result.errors), 1)
        self.assertIn("Bad Show", result.errors[0])
        self.assertEqual(len(result.episodes_found), 1)
        self.assertEqual(result.episodes_found[0].show_id, show_good.id)

    def test_scan_recent_missing_api_key_records_single_error(self):
        """Without an API key, playlist shows are not fetched and one error is recorded."""
        show_a = self._make_show(title="Show A")
        show_b = self._make_show(title="Show B")
        self._add_yt_link(show_a, playlist_id="PLa")
        self._add_yt_link(show_b, playlist_id="PLb")
        scanner = YoutubeScanner()

        with patch("shows.services.config_loader.load_youtube_api_key", return_value=None):
            with patch.object(scanner, "_fetch_videos_for_playlist") as mock_fetch:
                result = scanner.scan_recent([show_a, show_b])

        mock_fetch.assert_not_called()
        self.assertEqual(result.errors, ["YouTube API key not configured"])

    def test_scan_recent_missing_api_key_no_error_without_youtube_shows(self):
        """Without an API key and no YouTube shows, the scan is a silent no-op."""
        show = self._make_show()
        scanner = YoutubeScanner()

        with patch("shows.services.config_loader.load_youtube_api_key", return_value=None):
            result = scanner.scan_recent([show])

        self.assertEqual(result.errors, [])


class YoutubeEpisodeNumberTests(SimpleTestCase):

    def test_extracts_episode_numbers(self):
        scanner = YoutubeScanner(api_key="fake_key")
        cases = {
            "Episode 3 – 100 Days Later": 3,
            "【第5話】Test Show": 5,
            "Test Show S02E07": 7,
            "Test Show #12": 12,
            "Test Show - 08 [Multi-Subs]": 8,
            "Test Show Ep. 4": 4,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(scanner._extract_episode_number(title), expected)

    def test_rejects_out_of_range_numbers(self):
        scanner = YoutubeScanner(api_key="fake_key")
        self.assertIsNone(scanner._extract_episode_number("Episode 0"))
        self.assertIsNone(scanner._extract_episode_number("Test Show 2026"))


class YoutubeFetchPaginationTests(SimpleTestCase):

    def _response(self, payload):
        r = MagicMock()
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def test_follows_next_page_token(self):
        """All playlist pages are fetched before looking up video details."""
        page1 = {"items": [{"contentDetails": {"videoId": "v1"}}], "nextPageToken": "TOKEN2"}
        page2 = {"items": [{"contentDetails": {"videoId": "v2"}}]}
        videos = {"items": [_make_video("Episode 1", "v1"), _make_video("Episode 2", "v2")]}

        with patch(
            "shows.services.youtube_scanner.requests.get",
            side_effect=[self._response(page1), self._response(page2), self._response(videos)],
        ) as mock_get:
            result = YoutubeScanner(api_key="k")._fetch_videos_for_playlist("PLx", "k")

        self.assertEqual([v["id"] for v in result], ["v1", "v2"])
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["pageToken"], "TOKEN2")
        self.assertEqual(mock_get.call_args_list[2].kwargs["params"]["id"], "v1,v2")

    def test_empty_playlist_makes_no_video_request(self):
        with patch(
            "shows.services.youtube_scanner.requests.get",
            return_value=self._response({"items": []}),
        ) as mock_get:
            result = YoutubeScanner(api_key="k")._fetch_videos_for_playlist("PLx", "k")

        self.assertEqual(result, [])
        self.assertEqual(mock_get.call_count, 1)

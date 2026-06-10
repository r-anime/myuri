from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase

from shows.models import LinkType, Season, Show, ShowLink
from shows.services.crunchyroll_scanner import CrunchyrollScanner


def _make_episode(episode_number, title="Test Episode", days_ago=0, is_clip=False):
    """Build a minimal episode dict matching the Crunchyroll API response shape."""
    air_date = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return {
        "id": f"EP{episode_number:04d}",
        "title": title,
        "episode": str(episode_number),
        "episode_number": episode_number,
        "sequence_number": episode_number,
        "episode_air_date": air_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_clip": is_clip,
    }


class CrunchyrollScannerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.cr_link_type = LinkType.objects.create(
            name="Crunchyroll", slug="crunchyroll", category="stream"
        )

    def _make_show(self, **kwargs):
        defaults = dict(title="DAN DA DAN", title_en="", aliases="", has_source=False, season=self.season)
        defaults.update(kwargs)
        return Show.objects.create(**defaults)

    def _add_cr_link(self, show, series_id="GG5H5XQ0D"):
        ShowLink.objects.create(
            show=show,
            link_type=self.cr_link_type,
            url=f"https://www.crunchyroll.com/series/{series_id}",
        )

    def _scan(self, scanner, shows, episodes_by_show):
        """Run scan_recent with _get_bearer_token and _fetch_episodes_for_show mocked."""
        def fake_fetch(slug, headers):
            for show in shows:
                if episodes_by_show.get(show.id) is not None:
                    from shows.services.crunchyroll_scanner import _SERIES_ID_RE
                    for link in show.links.select_related("link_type").all():
                        if link.link_type.slug == "crunchyroll":
                            m = _SERIES_ID_RE.search(link.url)
                            if m and m.group(1) == slug:
                                return episodes_by_show[show.id]
            return []

        with patch.object(scanner, "_get_bearer_token", return_value="fake_token"):
            with patch.object(scanner, "_fetch_episodes_for_show", side_effect=fake_fetch):
                return scanner.scan_recent(shows)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_scan_recent_finds_episode(self):
        """scan_recent returns a FoundEpisode for a show with a CR ShowLink."""
        show = self._make_show()
        self._add_cr_link(show)
        scanner = CrunchyrollScanner()

        result = self._scan(scanner, [show], {show.id: [_make_episode(5, "Episode Five")]})

        self.assertEqual(len(result.episodes_found), 1)
        ep = result.episodes_found[0]
        self.assertEqual(ep.show_id, show.id)
        self.assertEqual(ep.episode_number, 5)
        self.assertEqual(ep.source, "Crunchyroll")
        self.assertEqual(ep.source_title, "Episode Five")
        self.assertIn("EP0005", ep.link)

    def test_scan_recent_shows_scanned_counts_cr_shows(self):
        """shows_scanned reflects only shows that have a CR ShowLink."""
        show_with = self._make_show(title="Show A")
        show_without = self._make_show(title="Show B")
        self._add_cr_link(show_with)
        scanner = CrunchyrollScanner()

        result = self._scan(scanner, [show_with, show_without], {show_with.id: []})

        self.assertEqual(result.shows_scanned, 1)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def test_scan_recent_skips_show_without_cr_link(self):
        """Shows with no Crunchyroll ShowLink are silently skipped."""
        show = self._make_show()
        scanner = CrunchyrollScanner()

        with patch.object(scanner, "_get_bearer_token", return_value="fake_token"):
            with patch.object(scanner, "_fetch_episodes_for_show") as mock_fetch:
                result = scanner.scan_recent([show])

        mock_fetch.assert_not_called()
        self.assertEqual(result.episodes_found, [])
        self.assertEqual(result.errors, [])

    def test_scan_recent_filters_clips(self):
        """Episodes marked is_clip=True are excluded."""
        show = self._make_show()
        self._add_cr_link(show)
        scanner = CrunchyrollScanner()

        clip = _make_episode(1, is_clip=True)
        result = self._scan(scanner, [show], {show.id: [clip]})

        self.assertEqual(result.episodes_found, [])

    def test_scan_recent_filters_missing_episode_number(self):
        """Episodes with no parseable episode number are excluded."""
        show = self._make_show()
        self._add_cr_link(show)
        scanner = CrunchyrollScanner()

        ep = _make_episode(1)
        ep["episode_number"] = None
        ep["episode"] = "OVA"
        result = self._scan(scanner, [show], {show.id: [ep]})

        self.assertEqual(result.episodes_found, [])

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_scan_recent_fetch_error_is_recorded(self):
        """A fetch failure for one show is recorded in errors and scanning continues."""
        show_bad  = self._make_show(title="Bad Show")
        show_good = self._make_show(title="Good Show")
        self._add_cr_link(show_bad,  series_id="BAAAAADDD1")
        self._add_cr_link(show_good, series_id="GOOOOOOOD1")
        scanner = CrunchyrollScanner()

        def fake_fetch(slug, headers):
            if slug == "BAAAAADDD1":
                raise ConnectionError("timeout")
            return [_make_episode(3)]

        with patch.object(scanner, "_get_bearer_token", return_value="fake_token"):
            with patch.object(scanner, "_fetch_episodes_for_show", side_effect=fake_fetch):
                result = scanner.scan_recent([show_bad, show_good])

        self.assertEqual(len(result.errors), 1)
        self.assertIn("Bad Show", result.errors[0])
        self.assertEqual(len(result.episodes_found), 1)
        self.assertEqual(result.episodes_found[0].show_id, show_good.id)

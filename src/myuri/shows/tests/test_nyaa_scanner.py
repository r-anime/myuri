import importlib
import importlib.util
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from django.test import TestCase

from shows.models import Season, Show
from shows.services.nyaa_scanner import NyaaScanner


def _make_torrent(title, published_parsed=None, link="https://nyaa.si/view/123"):
    """Build a minimal torrent dict matching the feedparser entry structure."""
    if published_parsed is None:
        published_parsed = time.gmtime()  # right now — within any max_age_days window
    return {
        "title": title,
        "published_parsed": published_parsed,
        "id": link,
    }


class NyaaScannerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")

        # Five shared shows used by test_find_matching_shows.
        # Each exercises a distinct matching path.
        cls.show_frieren    = Show.objects.create(title="Sousou no Frieren", title_en="Frieren: Beyond Journey's End", aliases="Frieren",     has_source=False, season=cls.season)
        cls.show_dungeon    = Show.objects.create(title="Dungeon Meshi",     title_en="",             aliases="Delicious in Dungeon\nMeshi",  has_source=False, season=cls.season)
        cls.show_kimetsu    = Show.objects.create(title="Kimetsu no Yaiba",  title_en="Demon Slayer", aliases="",                             has_source=False, season=cls.season)
        cls.show_rezero     = Show.objects.create(title="Re:Zero",           title_en="",             aliases="",                             has_source=False, season=cls.season)
        cls.show_pokemon    = Show.objects.create(title="Pokémon",           title_en="",             aliases="",                             has_source=False, season=cls.season)

    def _make_show(self, **kwargs):
        defaults = dict(
            title="Frieren",
            title_en="",
            aliases="",
            has_source=False,
            season=self.season,
        )
        defaults.update(kwargs)
        return Show.objects.create(**defaults)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_scan_recent_finds_matching_episode(self):
        """scan_recent returns a FoundEpisode when a torrent title matches a show."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()
        torrent = _make_torrent("[SubsPlease] Frieren - 05 [1080p].mkv")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 1)
        ep = result.episodes_found[0]
        self.assertEqual(ep.show_id, show.id)
        self.assertEqual(ep.show_title, show.title)
        self.assertEqual(ep.episode_number, 5)
        self.assertEqual(ep.source, "Nyaa")
        self.assertEqual(ep.link, "https://nyaa.si/view/123")

    def test_scan_recent_shows_scanned_count(self):
        """ScanResult.shows_scanned reflects the number of shows passed in."""
        shows = [
            self._make_show(title="Frieren"),
            self._make_show(title="Berserk"),
        ]
        scanner = NyaaScanner()

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[]):
            result = scanner.scan_recent(shows)

        self.assertEqual(result.shows_scanned, 2)
        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_matches_alias(self):
        """A show is found when the torrent title matches one of its aliases."""
        show = self._make_show(title="Sousou no Frieren", aliases="Frieren")
        scanner = NyaaScanner()
        torrent = _make_torrent("[SubsPlease] Frieren - 10 [1080p].mkv")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 1)
        self.assertEqual(result.episodes_found[0].episode_number, 10)

    # ------------------------------------------------------------------
    # Filtering / exclusion
    # ------------------------------------------------------------------

    def test_scan_recent_excludes_batch_releases(self):
        """Torrents with 'batch' in the title are excluded."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()
        torrent = _make_torrent("[SubsPlease] Frieren Batch [1080p]")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_excludes_bluray_releases(self):
        """Torrents with 'BD' / 'bluray' markers are excluded."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()
        torrent = _make_torrent("[Commie] Frieren - 05 [BDRip 1080p]")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_excludes_old_torrents(self):
        """Torrents older than max_age_days are ignored."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()
        old_published = datetime(2020, 1, 1).timetuple()
        torrent = _make_torrent("[SubsPlease] Frieren - 05 [1080p].mkv", published_parsed=old_published)

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_no_show_match_returns_empty(self):
        """Torrents that don't match any show produce no results."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()
        torrent = _make_torrent("[SubsPlease] Berserk - 05 [1080p].mkv")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_scan_recent_fetch_failure_returns_error(self):
        """When fetching the RSS feed raises, scan_recent returns a ScanResult with an error entry."""
        show = self._make_show(title="Frieren")
        scanner = NyaaScanner()

        with self.assertLogs("shows.services.nyaa_scanner", level="ERROR"), patch.object(scanner, "_fetch_recent_torrents", side_effect=Exception("Network error")):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Network error", result.errors[0])


    # ------------------------------------------------------------------
    # _normalize_name  (parameterized)
    # ------------------------------------------------------------------

    def test_normalize_name(self):
        scanner = NyaaScanner()
        cases = [
            # (input,                          expected,          description)
            ("Frieren",                        "frieren",         "lowercases"),
            ("Re:Zero",                        "re zero",         "removes special characters"),
            ("show_name",                      "show name",       "replaces underscores with spaces"),
            ("Overlord Season 2",              "overlord",        "strips season label"),
            ("Overlord Season 2 Part 1",       "overlord",        "strips season with part"),
            ("show   name",                    "show name",       "collapses whitespace"),
            ("  Frieren  ",                    "frieren",         "strips leading/trailing whitespace"),
            ("",                               "",                "empty string"),
        ]
        for value, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._normalize_name(value), expected)

    # ------------------------------------------------------------------
    # _strip_accents  (parameterized)
    # ------------------------------------------------------------------

    def test_strip_accents(self):
        scanner = NyaaScanner()
        cases = [
            # (input,      expected,   description)
            ("Pokémon",    "Pokemon",  "folds acute e"),
            ("Café",       "Cafe",     "folds acute e at end of word"),
            ("Otome Kaijuu Caraméliser","Otome Kaijuu Carameliser",     "folds acute e at end of word"),
            ("Frieren",    "Frieren",  "plain ASCII passthrough"),
            ("",           "",         "empty string"),
        ]
        for value, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._strip_accents(value), expected)

    # ------------------------------------------------------------------
    # _extract_episode_number  (parameterized)
    # ------------------------------------------------------------------

    def test_extract_episode_number(self):
        # Note: _extract_episode_number only extracts numbers from title strings.
        # Exclusion of batch/BD/PV releases is handled separately by _is_excluded;
        # these tests reflect what the method itself actually returns.
        scanner = NyaaScanner()
        cases = [
            # (title,                                     expected, description)
            ("[SubsPlease] Frieren - 05 [1080p].mkv",     5,        "[SubsPlease] ' - NN ' format"),
            ("[Erai-raws] Frieren - 12 [1080p].mkv",      12,       "[Erai-raws] format"),
            ("[DameDesuYo] Frieren - 03v2 [1080p].mkv",   3,        "[DameDesuYo] version-suffixed number"),
            ("[U3-Web] Frieren [EP07]",                   7,        "[U3-Web] [EPNN] bracket format"),
            ("[ember] Frieren s01e04",                    4,        "[ember] sNNeNN format"),
            ("Frieren - 08",                              8,        "bare ' - NN' fallback"),
            ("[SubsPlease] Frieren - 09 [1080p]",         9,        "SubsPlease without .mkv extension"),
            ("Frieren 5.mkv",                             5,        "number before .mkv extension"),
            ("Frieren Complete Series",                   None,     "no number pattern → None"),
            ("[SubsPlease] Frieren Batch [1080p]",        None,     "batch release → None (no extractable number)"),
        ]
        for title, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._extract_episode_number(title), expected)

    # ------------------------------------------------------------------
    # _is_excluded  (parameterized)
    # ------------------------------------------------------------------

    def test_is_excluded(self):
        scanner = NyaaScanner()
        cases = [
            # (title,                                                 expected, description)

            # .srt subtitle files
            ("Frieren - 05.srt",                                      True,  ".srt file"),

            # batch / volume / dub  (\b word-boundary, case-insensitive)
            ("[SubsPlease] Frieren Batch [1080p]",                    True,  "batch keyword"),
            ("[SubsPlease] Frieren Vol.1 [1080p]",                    True,  "vol. abbreviation"),
            ("[SubsPlease] Frieren Volume 1 [1080p]",                 True,  "volume keyword"),
            ("[SubsPlease] Frieren Dub [1080p]",                      True,  "dub keyword"),
            ("[SubsPlease] Frieren Dubbed [1080p]",                   True,  "dubbed keyword"),

            # BD / bluray
            ("[Commie] Frieren - 05 [BDRip 1080p]",                   True,  "BDRip"),
            ("[Commie] Frieren - 05 [BD 1080p]",                      True,  "BD standalone"),
            ("[Commie] Frieren - 05 [BDRemux]",                       True,  "BDRemux"),
            ("[Commie] Frieren - 05 [Bluray 1080p]",                  True,  "Bluray"),

            # PV / promotional video
            ("[SubsPlease] Frieren PV1 [1080p]",                      True,  "PV with number"),
            ("[SubsPlease] Frieren PV 2 [1080p]",                     True,  "PV with space and number"),

            # pre-air
            ("[SubsPlease] Frieren - 01 [Pre-Air]",                   True,  "pre-air hyphenated"),
            ("[SubsPlease] Frieren - 01 [Preair]",                    True,  "preair no hyphen"),

            # normal episode releases — must NOT be excluded
            ("[SubsPlease] Frieren - 05 [1080p].mkv",                 False, "standard episode"),
            ("[Erai-raws] Frieren - 12 [1080p].mkv",                  False, "Erai-raws episode"),
            ("[DameDesuYo] Frieren - 03v2 [1080p].mkv",               False, "versioned episode"),
            ("Frieren - 08",                                          False, "bare title no group"),
        ]
        for title, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._is_excluded(title), expected)

    # ------------------------------------------------------------------
    # _find_matching_shows  (parameterized)
    # ------------------------------------------------------------------

    def test_find_matching_shows(self):
        scanner = NyaaScanner()
        all_shows = [
            self.show_frieren,   # title="Frieren", title_en="Sousou no Frieren"
            self.show_dungeon,   # title="Dungeon Meshi", aliases="Delicious in Dungeon", "Meshi"
            self.show_kimetsu,   # title="Kimetsu no Yaiba", title_en="Demon Slayer"
            self.show_rezero,    # title="Re:Zero"
            self.show_pokemon,   # title="Pokémon"
        ]

        cases = [
            # (torrent_title, expected_ids, description)
            (
                "[SubsPlease] Frieren - 05 [1080p]",
                {self.show_frieren.id},
                "match by title",
            ),
            (
                "[SubsPlease] Sousou no Frieren - 12 [1080p]",
                {self.show_frieren.id, self.show_frieren.id},
                "longer title matches both: 'Frieren' (1 word) and 'Sousou no Frieren' (3 words) are both subsets",
            ),
            (
                "[SubsPlease] Dungeon Meshi - 01 [1080p]",
                {self.show_dungeon.id},
                "match by two-word title",
            ),
            (
                "[SubsPlease] Delicious in Dungeon - 02 [1080p]",
                {self.show_dungeon.id},
                "match by first alias",
            ),
            (
                "[SubsPlease] Meshi - 03 [1080p]",
                {self.show_dungeon.id},
                "match by short second alias",
            ),
            (
                "[SubsPlease] Demon Slayer - 05 [1080p]",
                {self.show_kimetsu.id},
                "match by English title",
            ),
            (
                "[SubsPlease] Re Zero - 03 [1080p]",
                {self.show_rezero.id},
                "match after special-character normalization (Re:Zero → re zero)",
            ),
            (
                "[SubsPlease] Berserk - 01 [1080p]",
                set(),
                "no match against any show",
            ),
            (
                "[SubsPlease] Kimetsu - 05 [1080p]",
                set(),
                "partial multi-word title does not match (missing 'no' and 'yaiba')",
            ),
            (
                "[SubsPlease] FRIEREN - 08 [1080p]",
                {self.show_frieren.id},
                "case-insensitive match",
            ),
            (
                "[SubsPlease] Pokemon - 05 [1080p]",
                {self.show_pokemon.id},
                "accent-insensitive match: unaccented torrent title matches accented show title (Pokémon)",
            ),
            (
                "[SubsPlease] Pokémon - 06 [1080p]",
                {self.show_pokemon.id},
                "accent-preserving match still works: accented torrent title matches accented show title",
            ),
        ]

        for torrent_title, expected_ids, description in cases:
            torrent = {"title": torrent_title}
            with self.subTest(description):
                matched = scanner._find_matching_shows(torrent, all_shows)
                self.assertEqual({s.id for s in matched}, expected_ids)

    def test_find_matching_shows_accent_insensitive_reverse(self):
        """An accented torrent title matches an unaccented show title/alias (reverse direction)."""
        show = self._make_show(title="Pokemon")
        scanner = NyaaScanner()
        torrent = {"title": "[SubsPlease] Pokémon - 07 [1080p]"}

        matched = scanner._find_matching_shows(torrent, [show])

        self.assertEqual({s.id for s in matched}, {show.id})

    def test_fetch_recent_torrents(self):
        """
        Calls the real Nyaa RSS feed.
        Verifies the feed returns a non-empty list of well-formed entries.

        This is an integration test — requires a network connection to nyaa.si
        and feedparser installed (pip install feedparser).

        Manually turn on printing if desired
        """
        scanner = NyaaScanner()
        torrents = scanner._fetch_recent_torrents()
        # print(f"\nFetched {len(torrents)} torrents from Nyaa RSS feed:")
        # for i, torrent in enumerate(torrents, start=1):
        #     title = torrent.get("title", "<no title>")
        #     link = torrent.get("id", torrent.get("link", "<no link>"))
        #     published = torrent.get("published", "<no date>")
        #     print(f"  {i:>3}. [{published}] {title}")
        #     print(f"       {link}")

        self.assertIsInstance(torrents, list)
        self.assertGreater(len(torrents), 0, "Expected at least one torrent from the live feed")

        first = torrents[0]
        self.assertIn("title", first, "Each entry should have a title")
        self.assertIn("published_parsed", first, "Each entry should have a parsed publication date")


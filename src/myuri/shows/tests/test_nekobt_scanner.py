import os
import time
import unittest
from datetime import datetime
from unittest.mock import patch

import feedparser
from django.test import TestCase

from shows.models import Season, Show
from shows.services.nekobt_scanner import NekobtScanner

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "nekobt_example.xml")


def _make_torrent(title, published_parsed=None, link="https://nekobt.to/torrents/123"):
    """Build a minimal torrent dict matching the feedparser entry structure."""
    if published_parsed is None:
        published_parsed = time.gmtime()  # right now — within any max_age_days window
    return {
        "title": title,
        "published_parsed": published_parsed,
        "id": link,
    }


class NekobtScannerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")

        cls.show_frieren = Show.objects.create(title="Sousou no Frieren", title_en="Frieren: Beyond Journey's End", aliases="Frieren", has_source=False, season=cls.season)
        cls.show_dungeon = Show.objects.create(title="Dungeon Meshi", title_en="", aliases="Delicious in Dungeon\nMeshi", has_source=False, season=cls.season)
        cls.show_kimetsu = Show.objects.create(title="Kimetsu no Yaiba", title_en="Demon Slayer", aliases="", has_source=False, season=cls.season)
        cls.show_pokemon = Show.objects.create(title="Pokémon", title_en="", aliases="", has_source=False, season=cls.season)

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
        show = self._make_show(title="Iron Wok Jan")
        scanner = NekobtScanner()
        torrent = _make_torrent("[TSPlease] Iron Wok Jan S01E03 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 1)
        ep = result.episodes_found[0]
        self.assertEqual(ep.show_id, show.id)
        self.assertEqual(ep.show_title, show.title)
        self.assertEqual(ep.episode_number, 3)
        self.assertEqual(ep.source, "Nekobt")
        self.assertEqual(ep.link, "https://nekobt.to/torrents/123")

    def test_scan_recent_shows_scanned_count(self):
        shows = [
            self._make_show(title="Frieren"),
            self._make_show(title="Berserk"),
        ]
        scanner = NekobtScanner()

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[]):
            result = scanner.scan_recent(shows)

        self.assertEqual(result.shows_scanned, 2)
        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_matches_alias(self):
        show = self._make_show(title="Sousou no Frieren", aliases="Frieren")
        scanner = NekobtScanner()
        torrent = _make_torrent("[ToonsHub] Frieren S01E10 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 1)
        self.assertEqual(result.episodes_found[0].episode_number, 10)

    # ------------------------------------------------------------------
    # Filtering / exclusion
    # ------------------------------------------------------------------

    def test_scan_recent_excludes_batch_releases(self):
        show = self._make_show(title="Frieren")
        scanner = NekobtScanner()
        torrent = _make_torrent("[ToonsHub] Frieren Batch S01 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_excludes_bluray_releases(self):
        show = self._make_show(title="Frieren")
        scanner = NekobtScanner()
        torrent = _make_torrent("[ToonsHub] Frieren S01E05 1080p BDRip AAC2.0 H.264 (Multi-Subs)")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_excludes_old_torrents(self):
        show = self._make_show(title="Frieren")
        scanner = NekobtScanner()
        old_published = datetime(2020, 1, 1).timetuple()
        torrent = _make_torrent("[ToonsHub] Frieren S01E05 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)", published_parsed=old_published)

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    def test_scan_recent_no_show_match_returns_empty(self):
        show = self._make_show(title="Frieren")
        scanner = NekobtScanner()
        torrent = _make_torrent("[ToonsHub] Berserk S01E05 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)")

        with patch.object(scanner, "_fetch_recent_torrents", return_value=[torrent]):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_scan_recent_fetch_failure_returns_error(self):
        show = self._make_show(title="Frieren")
        scanner = NekobtScanner()

        with self.assertLogs("shows.services.nekobt_scanner", level="ERROR"), patch.object(scanner, "_fetch_recent_torrents", side_effect=Exception("Network error")):
            result = scanner.scan_recent([show])

        self.assertEqual(len(result.episodes_found), 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Network error", result.errors[0])

    # ------------------------------------------------------------------
    # _normalize_name  (parameterized)
    # ------------------------------------------------------------------

    def test_normalize_name(self):
        scanner = NekobtScanner()
        cases = [
            ("Frieren", "frieren", "lowercases"),
            ("Re:Zero", "re zero", "removes special characters"),
            ("show_name", "show name", "replaces underscores with spaces"),
            ("Overlord Season 2", "overlord", "strips season label"),
            ("show   name", "show name", "collapses whitespace"),
            ("  Frieren  ", "frieren", "strips leading/trailing whitespace"),
            ("", "", "empty string"),
        ]
        for value, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._normalize_name(value), expected)

    # ------------------------------------------------------------------
    # _strip_accents  (parameterized)
    # ------------------------------------------------------------------

    def test_strip_accents(self):
        scanner = NekobtScanner()
        cases = [
            ("Pokémon", "Pokemon", "folds acute e"),
            ("Café", "Cafe", "folds acute e at end of word"),
            ("Frieren", "Frieren", "plain ASCII passthrough"),
            ("", "", "empty string"),
        ]
        for value, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._strip_accents(value), expected)

    # ------------------------------------------------------------------
    # _extract_episode_number  (parameterized)
    # ------------------------------------------------------------------

    def test_extract_episode_number(self):
        scanner = NekobtScanner()
        cases = [
            ("[TSPlease] Iron Wok Jan S01E03 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)", 3, "S01E03 format"),
            ("[ToonsHub] Wistoria Wand and Sword S02E12 1080p CR WEB-DL MULTi AAC2.0 H.264", 12, "S02E12 format"),
            ("[ToonsHub] Digimon Beatbreak S01E39 1080p CR WEB-DL AAC2.0 H.264 (English-Sub)", 39, "double-digit episode"),
            ("[ToonsHub] Frieren Complete Series", None, "no SxxEyy pattern -> None"),
        ]
        for title, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._extract_episode_number(title), expected)

    # ------------------------------------------------------------------
    # _is_excluded  (parameterized)
    # ------------------------------------------------------------------

    def test_is_excluded(self):
        scanner = NekobtScanner()
        cases = [
            ("[ToonsHub] Frieren Batch S01 1080p", True, "batch keyword"),
            ("[ToonsHub] Frieren Vol.1 1080p", True, "vol. abbreviation"),
            ("[ToonsHub] Frieren Dub S01E05 1080p", True, "dub keyword"),
            ("[ToonsHub] Frieren S01E05 1080p BDRip", True, "BDRip"),
            ("[ToonsHub] Frieren S01E05 1080p Bluray", True, "Bluray"),
            ("[ToonsHub] Frieren S01E05 1080p CR WEB-DL AAC2.0 H.264 (Multi-Subs)", False, "standard episode"),
        ]
        for title, expected, description in cases:
            with self.subTest(description):
                self.assertEqual(scanner._is_excluded(title), expected)

    # ------------------------------------------------------------------
    # _find_matching_shows  (parameterized)
    # ------------------------------------------------------------------

    def test_find_matching_shows(self):
        scanner = NekobtScanner()
        all_shows = [
            self.show_frieren,
            self.show_dungeon,
            self.show_kimetsu,
            self.show_pokemon,
        ]

        cases = [
            ("[ToonsHub] Frieren S01E05 1080p", {self.show_frieren.id}, "match by alias"),
            ("[ToonsHub] Sousou no Frieren S01E12 1080p", {self.show_frieren.id}, "match by title"),
            ("[ToonsHub] Dungeon Meshi S01E01 1080p", {self.show_dungeon.id}, "match by two-word title"),
            ("[ToonsHub] Delicious in Dungeon S01E02 1080p", {self.show_dungeon.id}, "match by first alias"),
            ("[ToonsHub] Demon Slayer S01E05 1080p", {self.show_kimetsu.id}, "match by English title"),
            ("[ToonsHub] Berserk S01E01 1080p", set(), "no match against any show"),
            ("[ToonsHub] Pokemon S01E05 1080p", {self.show_pokemon.id}, "accent-insensitive match"),
        ]

        for torrent_title, expected_ids, description in cases:
            torrent = {"title": torrent_title}
            with self.subTest(description):
                matched = scanner._find_matching_shows(torrent, all_shows)
                self.assertEqual({s.id for s in matched}, expected_ids)

    # ------------------------------------------------------------------
    # Fixture-based structural parse test (offline, no network)
    # ------------------------------------------------------------------

    def test_fixture_feed_parses_expected_fields(self):
        """
        Parses a captured real nekobt.to torznab response from disk and asserts
        feedparser extracts the standard RSS fields this scanner relies on
        (title, id/link, published_parsed), despite the torznab-namespaced
        <torznab:attr> extension elements in the document.
        """
        feed = feedparser.parse(FIXTURE_PATH)
        entries = feed.get("entries", [])

        self.assertGreater(len(entries), 0, "Fixture feed should contain entries")

        first = entries[0]
        self.assertIn("title", first)
        self.assertIn("S01E03", first["title"])
        self.assertEqual(first.get("id"), "https://nekobt.to/torrents/12483975658765")
        self.assertIsNotNone(first.get("published_parsed"))


class NekobtScannerLiveIntegrationTests(unittest.TestCase):

    def test_fetch_recent_torrents(self):
        """
        Calls the real nekobt.to torznab feed.

        This is an integration test — requires a network connection to nekobt.to
        and feedparser installed (pip install feedparser).
        """
        scanner = NekobtScanner()
        torrents = scanner._fetch_recent_torrents()

        self.assertIsInstance(torrents, list)
        self.assertGreater(len(torrents), 0, "Expected at least one torrent from the live feed")

        first = torrents[0]
        self.assertIn("title", first, "Each entry should have a title")
        self.assertIn("published_parsed", first, "Each entry should have a parsed publication date")

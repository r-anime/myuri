from datetime import datetime

from django.test import TestCase

from shows.models import Season, Show, ScanHistory, ScanEpisode
from shows.services.scan_result import FoundEpisode, ScanResult
from shows.services.scheduler_service import SchedulerService


class SchedulerServiceStoreScanEpisodesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.show = Show.objects.create(title="Test Show", season=cls.season, has_source=False)

    def _found(self, episode_number, source, link="https://example/1"):
        return FoundEpisode(
            show_id=self.show.id,
            show_title=self.show.title,
            episode_number=episode_number,
            source=source,
            source_title=f"[{source}] {self.show.title} - {episode_number}",
            found_at=datetime(2026, 1, 1, 12, 0, 0),
            link=link,
        )

    def test_merges_multiple_sources_into_one_row(self):
        scan_history = ScanHistory.objects.create(trigger_type="manual")
        scan_result = ScanResult(
            scan_time=datetime.now(),
            episodes_found=[self._found(5, "Nyaa"), self._found(5, "Nekobt")],
        )

        SchedulerService()._store_scan_episodes(scan_history, scan_result)

        episodes = ScanEpisode.objects.filter(scan=scan_history)
        self.assertEqual(episodes.count(), 1)
        self.assertEqual(episodes.first().source, "Nekobt, Nyaa")

    def test_separate_episodes_get_separate_rows(self):
        scan_history = ScanHistory.objects.create(trigger_type="manual")
        scan_result = ScanResult(
            scan_time=datetime.now(),
            episodes_found=[self._found(5, "Nyaa"), self._found(6, "Nyaa")],
        )

        SchedulerService()._store_scan_episodes(scan_history, scan_result)

        self.assertEqual(ScanEpisode.objects.filter(scan=scan_history).count(), 2)

    def test_single_source_row_unaffected(self):
        scan_history = ScanHistory.objects.create(trigger_type="manual")
        scan_result = ScanResult(
            scan_time=datetime.now(),
            episodes_found=[self._found(5, "Nekobt")],
        )

        SchedulerService()._store_scan_episodes(scan_history, scan_result)

        episode = ScanEpisode.objects.get(scan=scan_history)
        self.assertEqual(episode.source, "Nekobt")


class _FakeScanner:
    """Minimal stand-in for a scanner's scan_recent() return value."""

    def __init__(self, result):
        self._result = result

    def scan_recent(self, shows):
        return self._result


class SchedulerServiceScanAllSourcesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.show = Show.objects.create(title="Test Show", season=cls.season, has_source=False)

    def _found(self, episode_number, source):
        return FoundEpisode(
            show_id=self.show.id,
            show_title=self.show.title,
            episode_number=episode_number,
            source=source,
            source_title=f"[{source}] {self.show.title} - {episode_number}",
            found_at=datetime(2026, 1, 1, 12, 0, 0),
            link="https://example/1",
        )

    def _service_with_fakes(self, nyaa_result, nekobt_result, cr_result):
        service = SchedulerService()
        service._scanner = _FakeScanner(nyaa_result)
        service._nekobt_scanner = _FakeScanner(nekobt_result)
        service._crunchyroll_scanner = _FakeScanner(cr_result)
        return service

    def test_merges_episodes_from_all_three_scanners(self):
        service = self._service_with_fakes(
            nyaa_result=ScanResult(scan_time=datetime.now(), episodes_found=[self._found(1, "Nyaa")], shows_scanned=1),
            nekobt_result=ScanResult(scan_time=datetime.now(), episodes_found=[self._found(2, "Nekobt")], shows_scanned=1),
            cr_result=ScanResult(scan_time=datetime.now(), episodes_found=[self._found(3, "Crunchyroll")], shows_scanned=1),
        )

        result = service._scan_all_sources([self.show])

        sources = sorted(f.source for f in result.episodes_found)
        self.assertEqual(sources, ["Crunchyroll", "Nekobt", "Nyaa"])

    def test_merges_errors_from_all_three_scanners(self):
        service = self._service_with_fakes(
            nyaa_result=ScanResult(scan_time=datetime.now(), errors=["nyaa down"]),
            nekobt_result=ScanResult(scan_time=datetime.now(), errors=["nekobt down"]),
            cr_result=ScanResult(scan_time=datetime.now(), errors=["crunchyroll down"]),
        )

        result = service._scan_all_sources([self.show])

        self.assertEqual(
            set(result.errors), {"nyaa down", "nekobt down", "crunchyroll down"}
        )

    def test_shows_scanned_comes_from_nyaa_result(self):
        service = self._service_with_fakes(
            nyaa_result=ScanResult(scan_time=datetime.now(), shows_scanned=5),
            nekobt_result=ScanResult(scan_time=datetime.now(), shows_scanned=5),
            cr_result=ScanResult(scan_time=datetime.now(), shows_scanned=1),
        )

        result = service._scan_all_sources([self.show])

        self.assertEqual(result.shows_scanned, 5)

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

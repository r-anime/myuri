from datetime import datetime, timedelta
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from shows.models import Season, Show, ScanHistory, ScanEpisode, SchedulerConfig
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
        self.calls = 0

    def scan_recent(self, shows):
        self.calls += 1
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

    def _service_with_fakes(self, nyaa_result, nekobt_result, cr_result, yt_result=None):
        service = SchedulerService()
        service._scanner = _FakeScanner(nyaa_result)
        service._nekobt_scanner = _FakeScanner(nekobt_result)
        service._crunchyroll_scanner = _FakeScanner(cr_result)
        service._youtube_scanner = _FakeScanner(yt_result or ScanResult(scan_time=datetime.now()))
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

    def test_merges_youtube_episodes_and_errors(self):
        empty = ScanResult(scan_time=datetime.now())
        service = self._service_with_fakes(
            nyaa_result=empty, nekobt_result=empty, cr_result=empty,
            yt_result=ScanResult(
                scan_time=datetime.now(), episodes_found=[self._found(4, "YouTube")], errors=["youtube down"]
            ),
        )

        result = service._scan_all_sources([self.show])

        self.assertEqual([f.source for f in result.episodes_found], ["YouTube"])
        self.assertEqual(result.errors, ["youtube down"])

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

    def test_include_youtube_false_skips_youtube_scanner(self):
        service = self._service_with_fakes(
            nyaa_result=ScanResult(scan_time=datetime.now(), episodes_found=[self._found(1, "Nyaa")]),
            nekobt_result=ScanResult(scan_time=datetime.now()),
            cr_result=ScanResult(scan_time=datetime.now()),
            yt_result=ScanResult(scan_time=datetime.now(), episodes_found=[self._found(2, "YouTube")]),
        )

        result = service._scan_all_sources([self.show], include_youtube=False)

        self.assertEqual(service._youtube_scanner.calls, 0)
        self.assertEqual([f.source for f in result.episodes_found], ["Nyaa"])


class SchedulerServiceYoutubeGatingTests(TestCase):
    """Scheduled scans only include YouTube every youtube_interval_minutes."""

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.show = Show.objects.create(title="Test Show", season=cls.season, has_source=False)

    def setUp(self):
        self.config = SchedulerConfig.get_config()
        self.config.enabled = True
        self.config.youtube_interval_minutes = 5
        self.config.save()

    def _service(self):
        empty = ScanResult(scan_time=datetime.now())
        service = SchedulerService()
        service._scanner = _FakeScanner(empty)
        service._nekobt_scanner = _FakeScanner(empty)
        service._crunchyroll_scanner = _FakeScanner(empty)
        service._youtube_scanner = _FakeScanner(empty)
        service._auto_post_service = MagicMock()
        service._auto_post_service.determine_eligibility.return_value = []
        service._auto_post_service.post_eligible_episodes.return_value = MagicMock(
            posted=[], skipped=[], failed=[]
        )
        return service

    def _set_youtube_last_run(self, minutes_ago):
        self.config.youtube_last_run = timezone.now() - timedelta(minutes=minutes_ago)
        self.config.save()
        return self.config.youtube_last_run

    def test_first_run_scans_youtube_and_records_time(self):
        service = self._service()

        service.run_scheduled_scan()

        self.assertEqual(service._youtube_scanner.calls, 1)
        self.assertIsNotNone(SchedulerConfig.get_config().youtube_last_run)

    def test_skips_youtube_when_not_due(self):
        last_run = self._set_youtube_last_run(minutes_ago=1)
        service = self._service()

        service.run_scheduled_scan()

        self.assertEqual(service._youtube_scanner.calls, 0)
        self.assertEqual(service._scanner.calls, 1)
        self.assertEqual(SchedulerConfig.get_config().youtube_last_run, last_run)

    def test_scans_youtube_when_interval_elapsed(self):
        last_run = self._set_youtube_last_run(minutes_ago=5)
        service = self._service()

        service.run_scheduled_scan()

        self.assertEqual(service._youtube_scanner.calls, 1)
        self.assertGreater(SchedulerConfig.get_config().youtube_last_run, last_run)

    def test_tolerates_slight_scheduler_jitter(self):
        self.config.youtube_last_run = timezone.now() - timedelta(minutes=5) + timedelta(seconds=10)
        self.config.save()
        service = self._service()

        service.run_scheduled_scan()

        self.assertEqual(service._youtube_scanner.calls, 1)

    def test_manual_scan_always_scans_youtube_without_touching_last_run(self):
        last_run = self._set_youtube_last_run(minutes_ago=1)
        service = self._service()

        service.run_manual_scan()

        self.assertEqual(service._youtube_scanner.calls, 1)
        self.assertEqual(SchedulerConfig.get_config().youtube_last_run, last_run)

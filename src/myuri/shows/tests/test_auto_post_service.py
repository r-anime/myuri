from datetime import datetime

from django.test import TestCase

from shows.models import Season, Show, Episode
from shows.services.auto_post_service import AutoPostService, EpisodeEligibility
from shows.services.scan_result import ScanResult, FoundEpisode


def _make_scan_result(*found_episodes):
    return ScanResult(
        scan_time=datetime.now(),
        episodes_found=list(found_episodes),
        shows_scanned=1,
    )


def _found(show, episode_number, source="Nyaa"):
    return FoundEpisode(
        show_id=show.id,
        show_title=show.title,
        episode_number=episode_number,
        source=source,
        source_title=f"[Sub] {show.title} - {episode_number:02d} [1080p].mkv",
        found_at=datetime.now(),
        link=f"https://nyaa.si/view/{episode_number}",
    )


class DetermineEligibilityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="spring")
        cls.show = Show.objects.create(
            title="Tongari Boushi no Atelier",
            title_en="Witch Hat Atelier",
            aliases="",
            has_source=False,
            season=cls.season,
        )

    def _make_episode(self, number, order=None):
        if order is None:
            order = int(number)
        return Episode.objects.create(
            show=self.show,
            number=str(number),
            order=order,
        )

    # ------------------------------------------------------------------
    # Single episode cases
    # ------------------------------------------------------------------

    def test_first_episode_eligible_when_no_episodes_in_db(self):
        service = AutoPostService()
        result = service.determine_eligibility(_make_scan_result(_found(self.show, 1)))

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].is_eligible)
        self.assertEqual(result[0].reason, "ready_to_post")

    def test_next_episode_eligible(self):
        self._make_episode(1)
        service = AutoPostService()
        result = service.determine_eligibility(_make_scan_result(_found(self.show, 2)))

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].is_eligible)

    def test_already_posted_episode_not_eligible(self):
        self._make_episode(1)
        service = AutoPostService()
        result = service.determine_eligibility(_make_scan_result(_found(self.show, 1)))

        self.assertFalse(result[0].is_eligible)
        self.assertIn("already_posted", result[0].reason)

    def test_gap_not_eligible(self):
        self._make_episode(1)
        service = AutoPostService()
        result = service.determine_eligibility(_make_scan_result(_found(self.show, 3)))

        self.assertFalse(result[0].is_eligible)
        self.assertIn("gap_detected", result[0].reason)

    # ------------------------------------------------------------------
    # Multi-episode in single scan (the double-post bug scenario)
    # ------------------------------------------------------------------

    def test_ep1_and_ep2_both_eligible_when_no_episodes_in_db(self):
        """Both ep1 and ep2 found in same scan for a new show → ep1 then ep2 eligible."""
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(_found(self.show, 1), _found(self.show, 2))
        )

        self.assertEqual(len(result), 2)
        ep1_elig = next(r for r in result if r.scanned_episode == 1)
        ep2_elig = next(r for r in result if r.scanned_episode == 2)
        self.assertTrue(ep1_elig.is_eligible)
        self.assertTrue(ep2_elig.is_eligible)

    def test_ep2_before_ep1_in_scan_both_still_eligible(self):
        """Scan returns ep2 before ep1 (reversed order) - both must still be eligible."""
        service = AutoPostService()
        # ep2 listed first in scan result
        result = service.determine_eligibility(
            _make_scan_result(_found(self.show, 2), _found(self.show, 1))
        )

        self.assertEqual(len(result), 2)
        ep1_elig = next(r for r in result if r.scanned_episode == 1)
        ep2_elig = next(r for r in result if r.scanned_episode == 2)
        self.assertTrue(ep1_elig.is_eligible)
        self.assertTrue(ep2_elig.is_eligible)

    def test_gap_episode_not_eligible_when_ep1_is_pending(self):
        """ep1 + ep3 found (no ep2) - ep3 should not be eligible due to gap."""
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(_found(self.show, 1), _found(self.show, 3))
        )

        ep1_elig = next(r for r in result if r.scanned_episode == 1)
        ep3_elig = next(r for r in result if r.scanned_episode == 3)
        self.assertTrue(ep1_elig.is_eligible)
        self.assertFalse(ep3_elig.is_eligible)
        self.assertIn("gap_detected", ep3_elig.reason)

    def test_ep2_not_eligible_again_after_ep1_ep2_both_posted(self):
        """After ep1+ep2 posted in one scan, ep2 found in next scan must be already_posted."""
        # Simulate what happens after ep1+ep2 are posted (ep2 gets higher order since it
        # was processed second, which is the correct outcome of the fix).
        self._make_episode(number=1, order=1)
        self._make_episode(number=2, order=2)

        service = AutoPostService()
        result = service.determine_eligibility(_make_scan_result(_found(self.show, 2)))

        self.assertFalse(result[0].is_eligible)
        self.assertIn("already_posted", result[0].reason)

    def test_duplicate_found_episodes_deduplicated(self):
        """Same episode appearing twice in scan result counts only once."""
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(_found(self.show, 1), _found(self.show, 1))
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].is_eligible)
        self.assertEqual(result[0].sources, ["Nyaa"])

    # ------------------------------------------------------------------
    # sources aggregation (multiple scanners finding the same episode)
    # ------------------------------------------------------------------

    def test_sources_lists_the_single_contributing_scanner(self):
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(_found(self.show, 1, source="Nekobt"))
        )

        self.assertEqual(result[0].sources, ["Nekobt"])

    def test_sources_merged_when_multiple_scanners_find_same_episode(self):
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(
                _found(self.show, 1, source="Nekobt"),
                _found(self.show, 1, source="Nyaa"),
            )
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].is_eligible)
        self.assertEqual(result[0].sources, ["Nekobt", "Nyaa"])

    def test_sources_kept_separate_per_episode(self):
        service = AutoPostService()
        result = service.determine_eligibility(
            _make_scan_result(
                _found(self.show, 1, source="Nyaa"),
                _found(self.show, 2, source="Nekobt"),
            )
        )

        ep1 = next(r for r in result if r.scanned_episode == 1)
        ep2 = next(r for r in result if r.scanned_episode == 2)
        self.assertEqual(ep1.sources, ["Nyaa"])
        self.assertEqual(ep2.sources, ["Nekobt"])

from datetime import datetime

from django.test import TestCase

from shows.services.scan_result import ScanResult, FoundEpisode


def _found(show_id=1, show_title="Show", episode_number=1, source="Nyaa", link="https://example/1"):
    return FoundEpisode(
        show_id=show_id,
        show_title=show_title,
        episode_number=episode_number,
        source=source,
        source_title=f"[{source}] {show_title} - {episode_number}",
        found_at=datetime.now(),
        link=link,
    )


class ScanResultTests(TestCase):

    def test_group_by_episode_groups_matching_show_and_episode(self):
        f1 = _found(show_id=1, episode_number=5, source="Nyaa")
        f2 = _found(show_id=1, episode_number=5, source="Nekobt")
        f3 = _found(show_id=1, episode_number=6, source="Nyaa")
        result = ScanResult(scan_time=datetime.now(), episodes_found=[f1, f2, f3])

        groups = result.group_by_episode()

        self.assertEqual(set(groups.keys()), {(1, 5), (1, 6)})
        self.assertEqual(groups[(1, 5)], [f1, f2])
        self.assertEqual(groups[(1, 6)], [f3])

    def test_group_by_episode_separates_different_shows(self):
        f1 = _found(show_id=1, episode_number=1, source="Nyaa")
        f2 = _found(show_id=2, episode_number=1, source="Nyaa")
        result = ScanResult(scan_time=datetime.now(), episodes_found=[f1, f2])

        groups = result.group_by_episode()

        self.assertEqual(set(groups.keys()), {(1, 1), (2, 1)})

    def test_group_by_episode_empty(self):
        result = ScanResult(scan_time=datetime.now())
        self.assertEqual(result.group_by_episode(), {})

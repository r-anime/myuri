import unittest

from shows.services.crunchyroll_scanner import (
    CrunchyrollScanner,
    _CR_AUTH_URL as CR_AUTH_URL,
    _CR_SERIES_URL as CR_SERIES_URL,
    _CR_SEASON_URL as CR_SEASON_URL,
    _CR_USER_AGENT as CR_USER_AGENT,
)


class CrunchyrollApiTests(unittest.TestCase):

    def test_get_latest_episodes_by_slug(self):
        """Fetches the latest season's episodes for a show by Crunchyroll series slug."""
        slug = "GG5H5XQ0D"  # Dandadan
        scanner = CrunchyrollScanner()

        token = scanner._get_bearer_token()
        self.assertTrue(token, "Expected a non-empty Bearer token")

        headers = {"Authorization": "Bearer " + token, "User-Agent": CR_USER_AGENT}
        episodes = scanner._fetch_episodes_for_show(slug, headers)

        self.assertGreater(len(episodes), 0, f"No episodes returned for slug {slug!r}")

        print(f"\n[CR API] slug={slug}  episodes={len(episodes)}")
        print(f"\n{'Ep#':<8} {'Sequence#':<12} Title")
        print("-" * 72)
        for ep in episodes:
            print(f"{str(ep.get('episode_number', '?')):<8} {str(ep.get('sequence_number', '?')):<12} {ep.get('title', '')}")

        for ep in episodes:
            self.assertIn("episode_number", ep, f"episode_number missing from episode: {ep.get('title')}")

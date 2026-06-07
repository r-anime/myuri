import unittest
from datetime import datetime

import feedparser

# GENERAL_RSS_URL = "http://crunchyroll.com/rss/anime"
# GENERAL_RSS_URL = "http://crunchyroll.com/rss/anime/new"
# GENERAL_RSS_URL = "https://feeds.feedburner.com/crunchyroll/rss"
GENERAL_RSS_URL = "https://feeds.feedburner.com/crunchyroll/rss/anime"
EPISODE_RSS_URL = "http://crunchyroll.com/{id}.rss"


def _parse_entry(entry):
    """Returns (episode_number, timestamp, title) from a feedparser entry."""
    ep_num = entry.get("crunchyroll_episodenumber")
    try:
        ts = datetime(*entry.published_parsed[:6])
    except (TypeError, AttributeError):
        ts = None
    return ep_num, ts, entry.get("title", "")


class CrunchyrollRssTests(unittest.TestCase):

    def test_general_rss_feed(self):
        """Fetches the general Crunchyroll RSS feed and prints all episodes found."""
        feed = feedparser.parse(GENERAL_RSS_URL)

        entries = feed.get("entries", [])
        print(f"\n[General RSS] bozo={feed.bozo}  entries={len(entries)}")
        print(f"  URL: {GENERAL_RSS_URL}")

        episodes = []
        for entry in entries:
            ep_num, ts, title = _parse_entry(entry)
            episodes.append((ep_num, ts, title))

        print(f"\n{'Ep#':<8} {'Timestamp (UTC)':<22} Title")
        print("-" * 72)
        for ep_num, ts, title in episodes:
            ep_str = ep_num if ep_num is not None else "?"
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"
            print(f"{ep_str:<8} {ts_str:<22} {title}")

        self.assertGreater(len(entries), 0, "General RSS feed returned no entries")

    # def test_episode_rss_feed(self):
    #     """Probes a show-specific RSS feed to check if it still works."""
    #     show_id = "series/GT00371779"
    #     url = EPISODE_RSS_URL.format(id=show_id)
    #     feed = feedparser.parse(url)
    #
    #     entries = feed.get("entries", [])
    #     print(f"\n[Episode RSS] show={show_id}  bozo={feed.bozo}  entries={len(entries)}")
    #     print(f"  URL: {url}")
    #
    #     if entries:
    #         print(f"\n{'Ep#':<8} {'Timestamp (UTC)':<22} Title")
    #         print("-" * 72)
    #         for entry in entries:
    #             ep_num, ts, title = _parse_entry(entry)
    #             ep_str = ep_num if ep_num is not None else "?"
    #             ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"
    #             print(f"{ep_str:<8} {ts_str:<22} {title}")
    #     else:
    #         print("  -> No entries returned (feed appears broken or empty)")

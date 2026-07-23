import re
from types import SimpleNamespace

from django.test import TestCase

from shows.models import Season, Show, LinkType, ShowLink, Episode
from shows.services.config_loader import PostTemplates
from shows.services.reddit_service import RedditService


def _make_service(templates: PostTemplates) -> RedditService:
    """Create a RedditService with templates injected directly (no config.ini)."""
    svc = object.__new__(RedditService)
    svc._account_name = "test"
    svc._reddit = None
    svc._credentials = None
    svc._templates = templates
    return svc


def _default_templates(**overrides) -> PostTemplates:
    """Build a PostTemplates with sensible defaults, accepting overrides."""
    defaults = dict(
        title="{show_name} - Episode {episode} discussion",
        # \u2022 is the '•' seperator character we use.
        title_with_en="{show_name} \u2022 {show_name_en} - Episode {episode} discussion",
        title_postfix_final="[Final]",
        flair_id="",
        flair_text="",
        body=(
            "Show: {show_name}\n"
            "English: {show_name_en}\n"
            "Episode: {episode}\n"
            "Alt: {episode_alt_number}\n"
            "Name: {episode_name}\n"
            "Aliases: {aliases}\n"
            "Poll: {poll}\n"
            "Spoiler: {spoiler}\n"
            "Streams: {streams}\n"
            "Links: {links}\n"
            "Discussions: {discussions}"
        ),
        batch_thread_title="",
        batch_thread_title_with_en="",
        batch_thread_body="",
        formats={
            "stream": "* [{service_name}]({stream_link})",
            "link": "* [{site_name}]({link})",
            "discussion_header": "Episode|Link|Score",
            "discussion_align": ":-:|:-:|:-:",
            "discussion": "{episode}|[Link]({link})|[{score}]({poll_link})",
            "discussion_none": "*No discussions yet!*",
            "aliases": "Alternative names: *{aliases}*",
            "spoiler": "**Reminder:** Please do not discuss plot points not yet seen or skipped in the show.",
        },
    )
    defaults.update(overrides)
    return PostTemplates(**defaults)


# ---------------------------------------------------------------------------
# _build_title tests (no DB required)
# ---------------------------------------------------------------------------
class BuildTitleTests(TestCase):
    def test_japanese_only(self):
        svc = _make_service(_default_templates())
        show = SimpleNamespace(title="Sousou no Frieren", title_en="")
        result = svc._build_title(show, "5", is_final=False)
        self.assertEqual(result, "Sousou no Frieren - Episode 5 discussion")

    def test_with_english_title(self):
        svc = _make_service(_default_templates())
        show = SimpleNamespace(title="Sousou no Frieren", title_en="Frieren: Beyond Journey's End")
        result = svc._build_title(show, "5", is_final=False)
        self.assertEqual(
            result,
            "Sousou no Frieren \u2022 Frieren: Beyond Journey's End - Episode 5 discussion",
        )

    def test_final_episode_with_postfix(self):
        svc = _make_service(_default_templates(title_postfix_final="[Final]"))
        show = SimpleNamespace(title="Sousou no Frieren", title_en="")
        result = svc._build_title(show, "28", is_final=True)
        self.assertEqual(result, "Sousou no Frieren - Episode 28 discussion [Final]")

    def test_final_episode_no_postfix_configured(self):
        svc = _make_service(_default_templates(title_postfix_final=""))
        show = SimpleNamespace(title="Sousou no Frieren", title_en="")
        result = svc._build_title(show, "28", is_final=True)
        self.assertEqual(result, "Sousou no Frieren - Episode 28 discussion")

    def test_not_final_postfix_not_appended(self):
        svc = _make_service(_default_templates(title_postfix_final="[Final]"))
        show = SimpleNamespace(title="Sousou no Frieren", title_en="")
        result = svc._build_title(show, "5", is_final=False)
        self.assertNotIn("[Final]", result)


# ---------------------------------------------------------------------------
# _build_post_body tests (uses DB for Show, LinkType, ShowLink, Episode)
# ---------------------------------------------------------------------------
class BuildPostBodyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")

    def _make_show(self, **kwargs):
        defaults = dict(
            title="Sousou no Frieren",
            title_en="",
            aliases="",
            has_source=False,
            season=self.season,
        )
        defaults.update(kwargs)
        return Show.objects.create(**defaults)

    def test_basic_body_no_links_no_episodes(self):
        svc = _make_service(_default_templates())
        show = self._make_show()

        body = svc._build_post_body(show, "1")

        self.assertIn("Show: Sousou no Frieren", body)
        # show_name_en falls back to show.title when title_en is empty
        self.assertIn("English: Sousou no Frieren", body)
        self.assertIn("Episode: 1", body)
        self.assertIn("Streams: *None*", body)
        self.assertIn("Links: *None*", body)
        self.assertIn("*No discussions yet!*", body)
        self.assertIn("Aliases: \n", body)
        self.assertIn("Spoiler: \n", body)

    def test_body_with_streams_and_info_links(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        stream_type = LinkType.objects.create(name="Crunchyroll", slug="crunchyroll", category="stream")
        info_type = LinkType.objects.create(name="MyAnimeList", slug="mal", category="info")
        ShowLink.objects.create(show=show, link_type=stream_type, url="https://crunchyroll.com/frieren")
        ShowLink.objects.create(show=show, link_type=info_type, url="https://myanimelist.net/anime/12345")

        body = svc._build_post_body(show, "1")

        self.assertIn("* [Crunchyroll](https://crunchyroll.com/frieren)", body)
        self.assertIn("* [MyAnimeList](https://myanimelist.net/anime/12345)", body)
        self.assertNotIn("*None*", body)

    def test_body_with_episodes_discussions_table(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        Episode.objects.create(
            show=show, number="1", order=1,
            discussion_url="https://reddit.com/r/anime/comments/abc123/ep1",
        )
        Episode.objects.create(
            show=show, number="2", order=2,
            discussion_url="https://reddit.com/r/anime/comments/def456/ep2",
        )

        body = svc._build_post_body(show, "3")

        self.assertIn("Episode|Link|Score", body)
        self.assertIn("1|[Link](https://reddit.com/r/anime/comments/abc123/ep1)", body)
        self.assertIn("2|[Link](https://reddit.com/r/anime/comments/def456/ep2)", body)

    def test_body_with_current_episode_url(self):
        svc = _make_service(_default_templates())
        show = self._make_show()

        body = svc._build_post_body(
            show, "1",
            current_episode_url="https://reddit.com/r/anime/comments/xyz789/ep1",
            current_episode_number="1",
        )

        self.assertIn("Episode|Link|Score", body)
        self.assertIn("1|[Link](https://reddit.com/r/anime/comments/xyz789/ep1)", body)

    def test_body_with_aliases(self):
        svc = _make_service(_default_templates())
        show = self._make_show(aliases="Frieren Beyond Journey's End")

        body = svc._build_post_body(show, "1")

        self.assertIn("Alternative names: *Frieren Beyond Journey's End*", body)

    def test_body_with_spoiler(self):
        svc = _make_service(_default_templates())
        show = self._make_show(has_source=True)

        body = svc._build_post_body(show, "1")

        self.assertIn(
            "**Reminder:** Please do not discuss plot points not yet seen or skipped in the show.",
            body,
        )

    def test_body_without_spoiler(self):
        svc = _make_service(_default_templates())
        show = self._make_show(has_source=False)

        body = svc._build_post_body(show, "1")

        self.assertNotIn("Reminder", body)

    def test_body_with_english_title(self):
        svc = _make_service(_default_templates())
        show = self._make_show(title_en="Frieren: Beyond Journey's End")

        body = svc._build_post_body(show, "1")

        self.assertIn("English: Frieren: Beyond Journey's End", body)

    def test_scheduled_for_removal_episodes_excluded(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        Episode.objects.create(
            show=show, number="1", order=1,
            discussion_url="https://reddit.com/r/anime/comments/abc123/ep1",
        )
        Episode.objects.create(
            show=show, number="2", order=2,
            discussion_url="https://reddit.com/r/anime/comments/removed/ep2",
            scheduled_for_removal=True,
        )

        body = svc._build_post_body(show, "3")

        self.assertIn("1|[Link](https://reddit.com/r/anime/comments/abc123/ep1)", body)
        self.assertNotIn("removed", body)

    def test_subreddit_link_formatting(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        subreddit_type = LinkType.objects.create(name="Subreddit", slug="subreddit", category="info")
        ShowLink.objects.create(show=show, link_type=subreddit_type, url="/r/Frieren")

        body = svc._build_post_body(show, "1")

        self.assertIn("* [/r/Frieren](https://www.reddit.com/r/Frieren)", body)


# ---------------------------------------------------------------------------
# _format_discussions chunking tests (row cap / column wrap / episode cap)
# ---------------------------------------------------------------------------
class FormatDiscussionsChunkingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")

    def _make_show(self, **kwargs):
        defaults = dict(
            title="Sousou no Frieren",
            title_en="",
            aliases="",
            has_source=False,
            season=self.season,
        )
        defaults.update(kwargs)
        return Show.objects.create(**defaults)

    def _add_episodes(self, show, count, start=1):
        for i in range(start, start + count):
            Episode.objects.create(
                show=show, number=str(i), order=i,
                discussion_url=f"https://reddit.com/r/anime/comments/ep{i}/",
            )

    def test_under_row_cap_single_column_no_blank_lines(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 5)

        result = svc._format_discussions(show)
        lines = result.split("\n")

        self.assertEqual(lines[0], "Episode|Link|Score")
        self.assertEqual(lines[1], ":-:|:-:|:-:")
        self.assertEqual(len(lines), 2 + 5)
        self.assertNotIn("", lines)

    def test_exactly_at_row_cap_stays_single_column(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 13)

        result = svc._format_discussions(show)
        lines = result.split("\n")

        self.assertEqual(lines[0], "Episode|Link|Score")
        self.assertEqual(len(lines), 2 + 13)

    def test_over_row_cap_wraps_into_two_columns(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 14)

        result = svc._format_discussions(show)
        lines = result.split("\n")

        # Header/align repeated twice for 2 columns
        self.assertEqual(lines[0], "Episode|Link|Score|Episode|Link|Score")
        self.assertEqual(lines[1], ":-:|:-:|:-:|:-:|:-:|:-:")
        # 13 body rows max (row cap), second column only has 1 entry (episode 14)
        self.assertEqual(len(lines), 2 + 13)

        first_body_row = lines[2]
        # Column-major: row 1 has episode 1 (col 1) and episode 14 (col 2)
        self.assertTrue(first_body_row.startswith("1|[Link]"))
        self.assertIn("14|[Link]", first_body_row)

        last_body_row = lines[-1]
        # Row 13 has episode 13 in column 1 only, no second column entry
        self.assertTrue(last_body_row.startswith("13|[Link]"))
        self.assertEqual(last_body_row.count("|[Link]"), 1)

    def test_over_total_cap_drops_oldest_keeps_four_columns_max(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 60)

        result = svc._format_discussions(show)
        lines = result.split("\n")

        # Max 4 columns (52 episode cap / 13 rows)
        self.assertEqual(lines[0], "|".join(["Episode|Link|Score"] * 4))
        self.assertEqual(len(lines), 2 + 13)

        # Oldest 8 episodes (1-8) dropped; most recent 52 (9-60) kept
        episode_numbers = {int(n) for n in re.findall(r"(\d+)\|\[Link\]", result)}
        self.assertEqual(episode_numbers, set(range(9, 61)))

    def test_current_episode_included_and_can_push_out_oldest(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 55)

        result = svc._format_discussions(
            show,
            current_episode_url="https://reddit.com/r/anime/comments/current/",
            current_episode_number="56",
        )

        self.assertIn("56|[Link](https://reddit.com/r/anime/comments/current/)", result)
        # 55 existing + 1 current = 56 entries, cap 52 -> oldest 4 (episodes 1-4) dropped
        episode_numbers = {int(n) for n in re.findall(r"(\d+)\|\[Link\]", result)}
        self.assertEqual(episode_numbers, set(range(5, 57)))

    def test_additional_episodes_included_in_reshape(self):
        svc = _make_service(_default_templates())
        show = self._make_show()
        self._add_episodes(show, 3)

        result = svc._format_discussions(
            show,
            additional_episodes=[("4", "https://reddit.com/r/anime/comments/batch4/")],
        )

        self.assertIn("4|[Link](https://reddit.com/r/anime/comments/batch4/)", result)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2 + 4)

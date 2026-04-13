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

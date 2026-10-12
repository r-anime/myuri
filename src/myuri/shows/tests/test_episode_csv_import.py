from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from shows.models import Episode, Season, Show
from shows.services.episode_csv_import import (
    EpisodeCsvError, EpisodeRow, import_episodes, parse_episode_csv
)


class ParseEpisodeCsvTests(TestCase):

    def test_parses_comma_separated_rows(self):
        rows = parse_episode_csv("1,1,https://redd.it/a\n2,2,https://redd.it/b\n")

        self.assertEqual(rows, [
            EpisodeRow("1", 1, "https://redd.it/a"),
            EpisodeRow("2", 2, "https://redd.it/b"),
        ])

    def test_parses_tab_separated_rows(self):
        rows = parse_episode_csv("OVA1\t13\thttps://redd.it/a")

        self.assertEqual(rows, [EpisodeRow("OVA1", 13, "https://redd.it/a")])

    def test_skips_header_blank_lines_and_whitespace(self):
        rows = parse_episode_csv("episode_id, order, discussion url\n\n 0.5 , 1 , https://redd.it/a \n\n")

        self.assertEqual(rows, [EpisodeRow("0.5", 1, "https://redd.it/a")])

    def test_discussion_url_is_optional(self):
        rows = parse_episode_csv("1,1\n2,2,")

        self.assertEqual(rows, [EpisodeRow("1", 1), EpisodeRow("2", 2)])

    def test_empty_text_returns_no_rows(self):
        self.assertEqual(parse_episode_csv(""), [])

    def test_reports_every_bad_line(self):
        text = "\n".join([
            "1,1,https://redd.it/a",
            "2,two,https://redd.it/b",
            "3,3,not-a-url",
            "1,4,https://redd.it/c",
            "5",
            ",6,https://redd.it/d",
            "x" * 21 + ",7",
        ])

        with self.assertRaises(EpisodeCsvError) as ctx:
            parse_episode_csv(text)

        errors = ctx.exception.errors
        self.assertEqual(len(errors), 6)
        self.assertIn("Line 2", errors[0])
        self.assertIn("not a whole number", errors[0])
        self.assertIn("not a valid URL", errors[1])
        self.assertIn("more than once", errors[2])
        self.assertIn("got 1 columns", errors[3])
        self.assertIn("episode_id is empty", errors[4])
        self.assertIn("longer than 20", errors[5])


class ImportEpisodesTests(TestCase):

    def setUp(self):
        season = Season.objects.create(year=2026, season="winter")
        self.show = Show.objects.create(title="Show", season=season)

    def test_creates_new_episodes(self):
        counts = import_episodes(self.show, [
            EpisodeRow("1", 1, "https://redd.it/a"),
            EpisodeRow("2", 2, "https://redd.it/b"),
        ])

        self.assertEqual(counts, (2, 0))
        self.assertEqual(
            list(self.show.episodes.values_list("number", "order", "discussion_url")),
            [("1", 1, "https://redd.it/a"), ("2", 2, "https://redd.it/b")],
        )

    def test_updates_existing_episode_with_same_number(self):
        existing = Episode.objects.create(show=self.show, number="1", order=5, is_special=True)

        counts = import_episodes(self.show, [EpisodeRow("1", 1, "https://redd.it/a")])

        self.assertEqual(counts, (0, 1))
        existing.refresh_from_db()
        self.assertEqual(existing.order, 1)
        self.assertEqual(existing.discussion_url, "https://redd.it/a")
        self.assertTrue(existing.is_special)
        self.assertEqual(self.show.episodes.count(), 1)

    def test_does_not_touch_other_shows(self):
        other = Show.objects.create(title="Other", season=self.show.season)
        Episode.objects.create(show=other, number="1", order=1)

        import_episodes(self.show, [EpisodeRow("1", 1, "https://redd.it/a")])

        self.assertEqual(other.episodes.get().discussion_url, "")


class ShowAdminEpisodeCsvTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(user)
        self.season = Season.objects.create(year=2026, season="winter")

    def _post_data(self, csv_text):
        return {
            "title": "New Show",
            "title_en": "",
            "aliases": "",
            "season": self.season.pk,
            "enabled": "on",
            "episodes_csv": csv_text,
            "links-TOTAL_FORMS": 0,
            "links-INITIAL_FORMS": 0,
            "episodes-TOTAL_FORMS": 0,
            "episodes-INITIAL_FORMS": 0,
        }

    def test_add_page_shows_csv_field(self):
        response = self.client.get(reverse("admin:shows_show_add"))

        self.assertContains(response, 'name="episodes_csv"', count=1)

    def test_csv_field_sits_between_links_and_episodes_inlines(self):
        content = self.client.get(reverse("admin:shows_show_add")).content.decode()

        links = content.index('name="links-TOTAL_FORMS"')
        csv_field = content.index('name="episodes_csv"')
        episodes = content.index('name="episodes-TOTAL_FORMS"')
        self.assertLess(links, csv_field)
        self.assertLess(csv_field, episodes)

    def test_add_show_with_csv_creates_episodes(self):
        response = self.client.post(
            reverse("admin:shows_show_add"),
            self._post_data("1,1,https://redd.it/a\n2,2,https://redd.it/b"),
        )

        self.assertEqual(response.status_code, 302)
        show = Show.objects.get(title="New Show")
        self.assertEqual(show.episodes.count(), 2)

    def test_change_show_with_csv_updates_and_creates(self):
        show = Show.objects.create(title="New Show", season=self.season)
        Episode.objects.create(show=show, number="1", order=1)

        response = self.client.post(
            reverse("admin:shows_show_change", args=[show.pk]),
            self._post_data("1,1,https://redd.it/a\n2,2,https://redd.it/b"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(show.episodes.values_list("number", "discussion_url")),
            [("1", "https://redd.it/a"), ("2", "https://redd.it/b")],
        )

    def test_invalid_csv_blocks_save(self):
        response = self.client.post(
            reverse("admin:shows_show_add"),
            self._post_data("1,one,https://redd.it/a"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a whole number")
        self.assertFalse(Show.objects.exists())

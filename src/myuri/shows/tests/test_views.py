from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shows.models import Episode, Season, Show


class ShowsListStatusColorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.season = Season.objects.create(year=2026, season="winter")
        cls.staff_user = get_user_model().objects.create_user(
            username="staff", password="password", is_staff=True
        )

    def setUp(self):
        self.client.force_login(self.staff_user)

    def _get_status_color(self, show):
        response = self.client.get(reverse("shows:shows_list"))
        for _, season_shows in response.context["seasons_with_shows"]:
            for s in season_shows:
                if s.id == show.id:
                    return s.status_color
        self.fail(f"Show {show.id} not found in seasons_with_shows")

    def test_purple_when_completed_episode_count_meets_target(self):
        show = Show.objects.create(title="Completed Show", season=self.season, episode_count=2)
        Episode.objects.create(show=show, number="1", order=1)
        Episode.objects.create(show=show, number="2", order=2)

        self.assertEqual(self._get_status_color(show), "purple")

    def test_not_purple_when_removed_episodes_dont_count(self):
        show = Show.objects.create(title="Almost Done Show", season=self.season, episode_count=2)
        Episode.objects.create(show=show, number="1", order=1)
        Episode.objects.create(show=show, number="2", order=2, scheduled_for_removal=True)

        self.assertEqual(self._get_status_color(show), "grey")

    def test_no_purple_when_episode_count_unset(self):
        show = Show.objects.create(title="Unknown Total Show", season=self.season, episode_count=None)
        Episode.objects.create(show=show, number="1", order=1)

        self.assertEqual(self._get_status_color(show), "grey")

    def test_green_when_recently_discussed(self):
        show = Show.objects.create(title="Active Show", season=self.season, episode_count=12)
        Episode.objects.create(
            show=show,
            number="1",
            order=1,
            discussion_url="https://reddit.com/1",
            air_date=timezone.now() - timezone.timedelta(days=1),
        )

        self.assertEqual(self._get_status_color(show), "green")

    def test_orange_when_discussed_over_a_week_ago(self):
        show = Show.objects.create(title="Cooling Show", season=self.season, episode_count=12)
        Episode.objects.create(
            show=show,
            number="1",
            order=1,
            discussion_url="https://reddit.com/1",
            air_date=timezone.now() - timezone.timedelta(days=10),
        )

        self.assertEqual(self._get_status_color(show), "orange")

    def test_red_when_discussed_over_two_weeks_ago(self):
        show = Show.objects.create(title="Stale Show", season=self.season, episode_count=12)
        Episode.objects.create(
            show=show,
            number="1",
            order=1,
            discussion_url="https://reddit.com/1",
            air_date=timezone.now() - timezone.timedelta(days=20),
        )

        self.assertEqual(self._get_status_color(show), "red")

    def test_grey_when_no_discussion_posted(self):
        show = Show.objects.create(title="New Show", season=self.season, episode_count=12)

        self.assertEqual(self._get_status_color(show), "grey")

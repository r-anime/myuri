from unittest.mock import Mock, patch

from django.test import TestCase

from shows.services.notification_service import (
    COLOR_CUSTOM,
    COLOR_POSTED,
    COLOR_REMOVED,
    NotificationService,
)


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.service = NotificationService()
        self.mock_notifier = Mock()

        self.enabled_patcher = patch.object(
            NotificationService, "_is_discord_enabled", return_value=True
        )
        self.notifier_patcher = patch.object(
            NotificationService, "_get_discord_notifier", return_value=self.mock_notifier
        )
        self.enabled_patcher.start()
        self.notifier_patcher.start()
        self.addCleanup(self.enabled_patcher.stop)
        self.addCleanup(self.notifier_patcher.stop)

    def _sent_embed(self):
        self.mock_notifier.send.assert_called_once()
        (embeds,), _ = self.mock_notifier.send.call_args
        self.assertEqual(len(embeds), 1)
        return embeds[0]

    def test_notify_episode_posted_automated(self):
        self.service.notify_episode_posted(
            show_title="Test Show",
            episode="5",
            url="https://reddit.com/thread",
            is_automated=True,
        )

        embed = self._sent_embed()
        self.assertEqual(embed["title"], "Test Show - Episode 5")
        self.assertEqual(embed["url"], "https://reddit.com/thread")
        self.assertEqual(embed["description"], "\U0001F4FA New Episode Posted")
        self.assertEqual(embed["color"], COLOR_POSTED)
        self.assertNotIn("author", embed)

    def test_notify_episode_posted_by_user(self):
        self.service.notify_episode_posted(
            show_title="Test Show",
            episode="5",
            url="https://reddit.com/thread",
            user="someuser",
        )

        embed = self._sent_embed()
        self.assertEqual(embed["author"], {"name": "u/someuser"})
        self.assertEqual(embed["description"], "\U0001F4FA Episode Posted")
        self.assertEqual(embed["color"], COLOR_CUSTOM)

    def test_notify_episode_posted_automated_with_title_en(self):
        self.service.notify_episode_posted(
            show_title="Test Show",
            episode="5",
            url="https://reddit.com/thread",
            is_automated=True,
            show_title_en="Test Show English",
        )

        embed = self._sent_embed()
        self.assertEqual(
            embed["description"],
            "Test Show English\n\U0001F4FA New Episode Posted",
        )
        self.assertEqual(embed["color"], COLOR_POSTED)

    def test_notify_episode_posted_manual_with_title_en(self):
        self.service.notify_episode_posted(
            show_title="Test Show",
            episode="5",
            url="https://reddit.com/thread",
            show_title_en="Test Show English",
        )

        embed = self._sent_embed()
        self.assertEqual(
            embed["description"],
            "Test Show English\n\U0001F4FA Episode Posted",
        )
        self.assertEqual(embed["color"], COLOR_CUSTOM)

    def test_notify_custom_episode_posted(self):
        self.service.notify_custom_episode_posted(
            show_title="Test Show",
            discussion_subject="Movie Discussion",
            url="https://reddit.com/thread",
            user="someuser",
        )

        embed = self._sent_embed()
        self.assertEqual(embed["title"], "Test Show - Movie Discussion")
        self.assertEqual(embed["description"], "\U0001F4FA Custom Post")
        self.assertEqual(embed["color"], COLOR_CUSTOM)
        self.assertEqual(embed["author"], {"name": "u/someuser"})

    def test_notify_custom_episode_posted_with_title_en(self):
        self.service.notify_custom_episode_posted(
            show_title="Test Show",
            discussion_subject="Movie Discussion",
            url="https://reddit.com/thread",
            show_title_en="Test Show English",
        )

        embed = self._sent_embed()
        self.assertEqual(
            embed["description"],
            "Test Show English\n\U0001F4FA Custom Post",
        )
        self.assertEqual(embed["color"], COLOR_CUSTOM)

    def test_notify_episode_removed_with_url_and_user(self):
        self.service.notify_episode_removed(
            show_title="Test Show",
            episode="5",
            url="https://reddit.com/thread",
            user="someuser",
        )

        embed = self._sent_embed()
        self.assertEqual(embed["color"], COLOR_REMOVED)
        self.assertEqual(embed["url"], "https://reddit.com/thread")
        self.assertEqual(embed["author"], {"name": "u/someuser"})

    def test_notify_episode_removed_without_url_or_user(self):
        self.service.notify_episode_removed(show_title="Test Show", episode="5")

        embed = self._sent_embed()
        self.assertNotIn("url", embed)
        self.assertNotIn("author", embed)

    def test_no_send_when_discord_disabled(self):
        self.enabled_patcher.stop()
        with patch.object(NotificationService, "_is_discord_enabled", return_value=False):
            self.service.notify_episode_posted(
                show_title="Test Show", episode="5", url="https://reddit.com/thread"
            )
        self.enabled_patcher.start()

        self.mock_notifier.send.assert_not_called()

    def test_no_send_when_notifier_unavailable(self):
        self.notifier_patcher.stop()
        with patch.object(NotificationService, "_get_discord_notifier", return_value=None):
            self.service.notify_episode_posted(
                show_title="Test Show", episode="5", url="https://reddit.com/thread"
            )
        self.notifier_patcher.start()

        self.mock_notifier.send.assert_not_called()

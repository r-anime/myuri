from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from shows.services.discord_notifier import DiscordNotifier


class DiscordNotifierTests(TestCase):
    def setUp(self):
        self.notifier = DiscordNotifier("https://discord.example/webhook")
        self.embeds = [{"title": "Test", "color": 0x57F287}]

    @patch("shows.services.discord_notifier.requests.post")
    def test_send_posts_embeds_payload(self, mock_post):
        mock_post.return_value = Mock(status_code=204)

        result = self.notifier.send(self.embeds)

        self.assertTrue(result)
        mock_post.assert_called_once_with(
            "https://discord.example/webhook",
            json={"embeds": self.embeds},
            timeout=10,
        )

    @patch("shows.services.discord_notifier.requests.post")
    def test_send_returns_false_on_request_exception(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")

        result = self.notifier.send(self.embeds)

        self.assertFalse(result)

    @patch("shows.services.discord_notifier.requests.post")
    def test_send_returns_false_when_webhook_url_empty(self, mock_post):
        notifier = DiscordNotifier("")

        result = notifier.send(self.embeds)

        self.assertFalse(result)
        mock_post.assert_not_called()

"""Discord webhook notifier for episode posts."""
import logging

import requests

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Sends notifications to Discord via webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, embeds: list) -> bool:
        """Send embeds to Discord webhook.

        Returns True on success, False on failure.
        """
        if not self.webhook_url:
            logger.warning("Discord webhook URL is empty, skipping notification")
            return False

        try:
            response = requests.post(
                self.webhook_url,
                json={"embeds": embeds},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

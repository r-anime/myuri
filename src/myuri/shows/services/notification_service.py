"""Notification service for episode posts."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config_loader import WhitespaceFriendlyConfigParser

logger = logging.getLogger(__name__)

COLOR_POSTED = 0x57F287
COLOR_CUSTOM = 0x5865F2
COLOR_REMOVED = 0xED4245


def _get_project_root() -> Path:
    """Get the project root directory (where config files live)."""
    return Path(__file__).parent.parent.parent.parent.parent


def _truncate(text: str, length: int = 256) -> str:
    """Truncate text to fit Discord embed field limits."""
    return text if len(text) <= length else text[: length - 1] + "…"


class NotificationService:
    """Orchestrates notifications across multiple backends."""

    def __init__(self):
        self._discord_notifier = None
        self._webhook_url = None
        self._config_loaded = False

    def _load_config(self):
        """Load Discord webhook URL from config.ini."""
        if self._config_loaded:
            return

        config_path = _get_project_root() / "config.ini"
        if not config_path.exists():
            logger.warning("config.ini not found, Discord notifications disabled")
            self._config_loaded = True
            return

        parsed = WhitespaceFriendlyConfigParser()
        parsed.read(config_path, encoding="utf-8")

        if "discord" in parsed:
            self._webhook_url = parsed["discord"].get("webhook_url", "").strip()

        self._config_loaded = True

    def _get_discord_notifier(self):
        """Lazy load DiscordNotifier."""
        if self._discord_notifier is None:
            self._load_config()
            if self._webhook_url:
                from .discord_notifier import DiscordNotifier
                self._discord_notifier = DiscordNotifier(self._webhook_url)
        return self._discord_notifier

    def _is_discord_enabled(self) -> bool:
        """Check if Discord notifications are enabled in admin config."""
        try:
            from ..models import NotificationConfig
            config = NotificationConfig.get_config()
            return config.discord_enabled
        except Exception as e:
            logger.warning(f"Failed to load NotificationConfig: {e}")
            return False

    def notify_episode_posted(
        self,
        show_title: str,
        episode: str,
        url: str,
        user: Optional[str] = None,
        is_automated: bool = False,
        show_title_en: Optional[str] = None,
    ):
        """Send notification when an episode is posted.

        Args:
            show_title: Name of the show
            episode: Episode number or subject
            url: Reddit discussion thread URL
            user: Username who triggered the post (None for automated)
            is_automated: True if posted by scheduled scanner
            show_title_en: English title of the show, if known
        """
        if not self._is_discord_enabled():
            return

        notifier = self._get_discord_notifier()
        if notifier is None:
            logger.debug("Discord notifier not available (no webhook URL)")
            return

        description = "\U0001F4FA New Episode Posted" if is_automated else "\U0001F4FA Episode Posted"
        if show_title_en:
            description = f"{show_title_en}\n{description}"

        embed = {
            "title": _truncate(f"{show_title} - Episode {episode}"),
            "url": url,
            "description": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "color": COLOR_POSTED if is_automated else COLOR_CUSTOM,
        }
        if user:
            embed["author"] = {"name": f"u/{user}"}

        notifier.send([embed])

    def notify_custom_episode_posted(
        self,
        show_title: str,
        discussion_subject: str,
        url: str,
        user: Optional[str] = None,
        show_title_en: Optional[str] = None,
    ):
        """Send notification when a custom episode is posted.

        Args:
            show_title: Name of the show
            discussion_subject: Custom subject/title of the discussion
            url: Reddit discussion thread URL
            user: Username who triggered the post
            show_title_en: English title of the show, if known
        """
        if not self._is_discord_enabled():
            return

        notifier = self._get_discord_notifier()
        if notifier is None:
            logger.debug("Discord notifier not available (no webhook URL)")
            return

        description = "\U0001F4FA Custom Post"
        if show_title_en:
            description = f"{show_title_en}\n{description}"

        embed = {
            "title": _truncate(f"{show_title} - {discussion_subject}"),
            "url": url,
            "description": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "color": COLOR_CUSTOM,
        }
        if user:
            embed["author"] = {"name": f"u/{user}"}

        notifier.send([embed])

    def notify_episode_removed(
        self,
        show_title: str,
        episode: str,
        url: Optional[str] = None,
        user: Optional[str] = None,
    ):
        """Send notification when an episode thread is removed.

        Args:
            show_title: Name of the show
            episode: Episode number
            url: Reddit discussion thread URL (if available)
            user: Username who triggered the removal
        """
        if not self._is_discord_enabled():
            return

        notifier = self._get_discord_notifier()
        if notifier is None:
            logger.debug("Discord notifier not available (no webhook URL)")
            return

        embed = {
            "title": _truncate(f"{show_title} - Episode {episode}"),
            "description": "\U0001F5D1 Episode Removed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "color": COLOR_REMOVED,
        }
        if url:
            embed["url"] = url
        if user:
            embed["author"] = {"name": f"u/{user}"}

        notifier.send([embed])

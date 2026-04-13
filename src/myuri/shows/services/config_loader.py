"""Configuration loader for Reddit credentials and post templates."""

import configparser
from pathlib import Path
from dataclasses import dataclass


class WhitespaceFriendlyConfigParser(configparser.ConfigParser):
    """ConfigParser that strips quotes from values."""

    def get(self, section, option, *args, **kwargs):
        val = super().get(section, option, *args, **kwargs)
        return val.strip('"')


@dataclass
class RedditCredentials:
    """Reddit API credentials for a single account."""

    username: str
    password: str
    oauth_key: str
    oauth_secret: str
    subreddit: str
    useragent: str


@dataclass
class PostTemplates:
    """Templates for Reddit posts."""

    title: str
    title_with_en: str
    title_postfix_final: str
    flair_id: str
    flair_text: str
    body: str
    batch_thread_title: str
    batch_thread_title_with_en: str
    batch_thread_body: str
    formats: dict


def _get_project_root() -> Path:
    """Get the project root directory (where config files live)."""
    # Navigate from src/myuri/shows/services/ up to project root
    return Path(__file__).parent.parent.parent.parent.parent


def load_reddit_config(account_name: str = "reddit_episode_poster") -> RedditCredentials:
    """Load Reddit credentials from config_reddit.ini.

    Args:
        account_name: Section name in config_reddit.ini (default: reddit_episode_poster)

    Returns:
        RedditCredentials dataclass with account credentials

    Raises:
        FileNotFoundError: If config_reddit.ini doesn't exist
        KeyError: If account_name section doesn't exist
        ValueError: If required credentials are missing
    """
    config_path = _get_project_root() / "config.ini"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Reddit config not found at {config_path}. "
            "Copy config.ini.example to config.ini and fill in credentials."
        )

    parsed = WhitespaceFriendlyConfigParser()
    parsed.read(config_path, encoding="utf-8")

    if account_name not in parsed:
        raise KeyError(f"Account '{account_name}' not found in config_reddit.ini")

    sec = parsed[account_name]

    # Validate required fields
    required = ["username", "password", "oauth_key", "oauth_secret", "subreddit", "useragent"]
    missing = [f for f in required if not sec.get(f, "").strip()]
    if missing:
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    return RedditCredentials(
        username=sec.get("username"),
        password=sec.get("password"),
        oauth_key=sec.get("oauth_key"),
        oauth_secret=sec.get("oauth_secret"),
        subreddit=sec.get("subreddit"),
        useragent=sec.get("useragent"),
    )


def load_moderator_config() -> RedditCredentials | None:
    """Load Reddit moderator credentials from config.ini.

    Returns:
        RedditCredentials dataclass if credentials are configured, None otherwise.
        Returns None if config file doesn't exist, section is missing, or
        any required credentials are empty.
    """
    config_path = _get_project_root() / "config.ini"

    if not config_path.exists():
        return None

    parsed = WhitespaceFriendlyConfigParser()
    parsed.read(config_path, encoding="utf-8")

    if "reddit_moderator" not in parsed:
        return None

    sec = parsed["reddit_moderator"]

    # Check if all required fields are present and non-empty
    required = ["username", "password", "oauth_key", "oauth_secret", "subreddit", "useragent"]
    for field in required:
        if not sec.get(field, "").strip():
            return None

    return RedditCredentials(
        username=sec.get("username"),
        password=sec.get("password"),
        oauth_key=sec.get("oauth_key"),
        oauth_secret=sec.get("oauth_secret"),
        subreddit=sec.get("subreddit"),
        useragent=sec.get("useragent"),
    )


def load_post_templates() -> PostTemplates:
    """Load post templates from config.ini.

    Returns:
        PostTemplates dataclass with template strings

    Raises:
        FileNotFoundError: If config.ini doesn't exist
    """
    config_path = _get_project_root() / "config.ini"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found at {config_path}")

    parsed = WhitespaceFriendlyConfigParser()
    parsed.read(config_path, encoding="utf-8")

    if "post" not in parsed:
        raise KeyError("'post' section not found in config.ini")

    sec = parsed["post"]

    # Load format strings
    formats = {}
    for key in sec:
        if key.startswith("format_") and len(key) > 7:
            formats[key[7:]] = sec[key]

    return PostTemplates(
        title=sec.get("title", ""),
        title_with_en=sec.get("title_with_en", ""),
        title_postfix_final=sec.get("title_postfix_final", ""),
        flair_id=sec.get("flair_id", ""),
        flair_text=sec.get("flair_text", ""),
        body=sec.get("body", ""),
        batch_thread_title=sec.get("batch_thread_title", ""),
        batch_thread_title_with_en=sec.get("batch_thread_title_with_en", ""),
        batch_thread_body=sec.get("batch_thread_body", ""),
        formats=formats,
    )

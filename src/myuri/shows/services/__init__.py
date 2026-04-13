# Explicit imports only - praw dependency is optional until RedditService is used
from .config_loader import load_reddit_config, load_post_templates, load_moderator_config

# Lazy import for RedditService to avoid requiring praw at module load time
# Lazy import for NyaaScanner to avoid requiring feedparser at module load time
def __getattr__(name):
    if name == "RedditService":
        from .reddit_service import RedditService
        return RedditService
    if name == "NyaaScanner":
        from .nyaa_scanner import NyaaScanner
        return NyaaScanner
    if name == "NyaaSpecificScanner":
        from .nyaa_specific import NyaaSpecificScanner
        return NyaaSpecificScanner
    if name == "ScanResult":
        from .scan_result import ScanResult
        return ScanResult
    if name == "AutoPostService":
        from .auto_post_service import AutoPostService
        return AutoPostService
    if name == "EpisodeEligibility":
        from .auto_post_service import EpisodeEligibility
        return EpisodeEligibility
    if name == "AutoPostResult":
        from .auto_post_service import AutoPostResult
        return AutoPostResult
    if name == "SchedulerService":
        from .scheduler_service import SchedulerService
        return SchedulerService
    if name == "NotificationService":
        from .notification_service import NotificationService
        return NotificationService
    if name == "DiscordNotifier":
        from .discord_notifier import DiscordNotifier
        return DiscordNotifier
    if name == "RedditModeratorService":
        from .reddit_moderator_service import RedditModeratorService
        return RedditModeratorService
    if name in (
        "import_shows_to_database",
        "get_season_config_files",
        "delete_season_shows",
        "parse_season_from_filename",
    ):
        from . import season_config_loader
        return getattr(season_config_loader, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "load_reddit_config",
    "load_post_templates",
    "load_moderator_config",
    "RedditService",
    "NyaaScanner",
    "NyaaSpecificScanner",
    "ScanResult",
    "AutoPostService",
    "EpisodeEligibility",
    "AutoPostResult",
    "SchedulerService",
    "NotificationService",
    "DiscordNotifier",
    "RedditModeratorService",
    "EpisodeDiscoveryService",
    "DiscoveryResult",
    "DiscoveryPosted",
    "DiscoverySkipped",
    "DiscoveryFailed",
    "import_shows_to_database",
    "get_season_config_files",
    "delete_season_shows",
    "parse_season_from_filename",
]

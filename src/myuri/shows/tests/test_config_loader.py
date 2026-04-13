from django.test import TestCase

from shows.services.config_loader import (
    WhitespaceFriendlyConfigParser,
    RedditCredentials,
    PostTemplates,
    load_reddit_config,
    load_moderator_config,
    load_post_templates,
)


class ConfigLoaderTests(TestCase):
    pass

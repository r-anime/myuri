"""Reddit moderator service for removing mistakenly-posted discussion threads."""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class RedditModeratorService:
    """Service for Reddit moderator actions like removing threads."""

    def __init__(self):
        self._reddit = None
        self._credentials = None

    def _get_reddit(self):
        """Lazy-load the PRAW Reddit instance."""
        if self._reddit is None:
            from .config_loader import load_moderator_config
            import praw

            self._credentials = load_moderator_config()
            if self._credentials is None:
                return None

            self._reddit = praw.Reddit(
                client_id=self._credentials.oauth_key,
                client_secret=self._credentials.oauth_secret,
                username=self._credentials.username,
                password=self._credentials.password,
                user_agent=self._credentials.useragent,
            )

        return self._reddit

    def is_available(self) -> bool:
        """Check if moderator credentials are configured.

        Returns:
            True if moderator credentials are available, False otherwise.
        """
        from .config_loader import load_moderator_config
        return load_moderator_config() is not None

    @staticmethod
    def extract_submission_id(url: str) -> Optional[str]:
        """Extract Reddit submission ID from a discussion URL.

        Supports various Reddit URL formats:
        - https://www.reddit.com/r/anime/comments/abc123/title/
        - https://reddit.com/r/anime/comments/abc123/title/
        - https://old.reddit.com/r/anime/comments/abc123/
        - https://redd.it/abc123

        Args:
            url: Reddit discussion URL

        Returns:
            Submission ID if found, None otherwise.
        """
        if not url:
            return None

        # Pattern for standard Reddit URLs
        # Matches: /comments/SUBMISSION_ID/
        standard_pattern = r"/comments/([a-zA-Z0-9]+)"
        match = re.search(standard_pattern, url)
        if match:
            return match.group(1)

        # Pattern for short redd.it URLs
        # Matches: redd.it/SUBMISSION_ID
        short_pattern = r"redd\.it/([a-zA-Z0-9]+)"
        match = re.search(short_pattern, url)
        if match:
            return match.group(1)

        return None

    def remove_thread(self, discussion_url: str) -> dict:
        """Remove a Reddit discussion thread.

        Uses submission.mod.remove() to remove the thread as a moderator action.
        This hides the thread from the subreddit but doesn't delete it entirely.

        Args:
            discussion_url: URL of the Reddit discussion thread to remove

        Returns:
            dict with keys:
            - success: bool indicating if removal was successful
            - message: str with success/error message
            - submission_id: str submission ID if found

        Raises:
            No exceptions are raised; errors are returned in the response dict.
        """
        # Check if service is available
        reddit = self._get_reddit()
        if reddit is None:
            return {
                "success": False,
                "message": "Moderator functionality not configured",
                "submission_id": None,
            }

        # Extract submission ID
        submission_id = self.extract_submission_id(discussion_url)
        if submission_id is None:
            return {
                "success": False,
                "message": f"Could not extract submission ID from URL: {discussion_url}",
                "submission_id": None,
            }

        try:
            # Get the submission and remove it
            submission = reddit.submission(id=submission_id)
            submission.mod.remove()

            logger.info(f"Removed Reddit thread: {submission_id} ({discussion_url})")

            return {
                "success": True,
                "message": f"Thread {submission_id} removed successfully",
                "submission_id": submission_id,
            }

        except Exception as e:
            logger.error(f"Failed to remove Reddit thread {submission_id}: {e}")
            return {
                "success": False,
                "message": str(e),
                "submission_id": submission_id,
            }

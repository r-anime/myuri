"""Reddit service for posting episode discussion threads."""

import logging
import re
import praw
from typing import Optional, List, Tuple

from .config_loader import load_reddit_config, load_post_templates, RedditCredentials, PostTemplates

logger = logging.getLogger(__name__)

# Maximum number of previous episodes to update when posting a new episode
MAX_EPISODES_TO_UPDATE = 30


class RedditService:
    """Service for interacting with Reddit API via PRAW."""

    def __init__(self, account_name: str = "reddit_episode_poster"):
        """Initialize the Reddit service.

        Args:
            account_name: Section name in config_reddit.ini to use for credentials
        """
        self._account_name = account_name
        self._reddit: Optional[praw.Reddit] = None
        self._credentials: Optional[RedditCredentials] = None
        self._templates: Optional[PostTemplates] = None

    @property
    def reddit(self) -> praw.Reddit:
        """Lazy-load and return PRAW Reddit instance."""
        if self._reddit is None:
            self._credentials = load_reddit_config(self._account_name)
            self._reddit = praw.Reddit(
                client_id=self._credentials.oauth_key,
                client_secret=self._credentials.oauth_secret,
                username=self._credentials.username,
                password=self._credentials.password,
                user_agent=self._credentials.useragent,
            )
        return self._reddit

    @property
    def subreddit(self) -> str:
        """Get the target subreddit name."""
        if self._credentials is None:
            self._credentials = load_reddit_config(self._account_name)
        return self._credentials.subreddit

    @property
    def templates(self) -> PostTemplates:
        """Lazy-load and return post templates."""
        if self._templates is None:
            self._templates = load_post_templates()
        return self._templates

    def _short_url(self, submission) -> str:
        """Build the short-form discussion URL (Reddit resolves it without the title slug)."""
        return f"https://www.reddit.com/r/{self.subreddit}/comments/{submission.id}/"

    def submit_episode_post(self, show, episode_number: str, is_final: bool = False) -> dict:
        """Submit an episode discussion post to Reddit.

        Args:
            show: Show model instance
            episode_number: Episode number (string to support "OVA1", "0.5", etc.)
            is_final: Whether this is the final episode

        Returns:
            dict with 'url', 'id', and 'updated_count' of previous episodes updated
        """
        title = self._build_title(show, episode_number, is_final)
        body = self._build_post_body(show, episode_number)

        subreddit = self.reddit.subreddit(self.subreddit)

        # Submit the post
        submission = subreddit.submit(
            title=title,
            selftext=body,
            flair_id=self.templates.flair_id or None,
            flair_text=self.templates.flair_text or None,
        )

        short_url = self._short_url(submission)

        # Edit the post to include itself in the discussions table
        updated_body = self._build_post_body(
            show,
            episode_number,
            current_episode_url=short_url,
            current_episode_number=episode_number,
        )
        submission.edit(updated_body)

        # Update previous episode threads with latest show info and discussions
        updated_count = self._update_previous_episodes(
            show,
            new_episode_url=short_url,
            new_episode_number=episode_number,
        )

        return {
            "url": short_url,
            "id": submission.id,
            "updated_count": updated_count,
        }

    def submit_episode_batch(
        self,
        show,
        start_episode: int,
        end_episode: int,
    ) -> dict:
        """Submit a batch of episode discussion posts to Reddit.

        Posts a megathread first, then all episodes from start to end, then edits
        all of them to include the complete discussions table with all episode URLs.

        Args:
            show: Show model instance
            start_episode: First episode number to post
            end_episode: Last episode number to post

        Returns:
            dict with 'episodes' list of (number, url) tuples, 'episodes_posted' count,
            'megathread' tuple of (number, url), and 'updated_count' of previous episodes updated
        """
        subreddit = self.reddit.subreddit(self.subreddit)
        batch_episodes: List[Tuple[int, str, praw.models.Submission]] = []

        # Phase 1: Post megathread first
        megathread_number = f"Megathread {start_episode}-{end_episode}"
        megathread_title = self._build_megathread_title(show, start_episode, end_episode)
        megathread_body = self._build_megathread_body(show, start_episode, end_episode)

        megathread_submission = subreddit.submit(
            title=megathread_title,
            selftext=megathread_body,
            flair_id=self.templates.flair_id or None,
            flair_text=self.templates.flair_text or None,
        )
        megathread_short_url = self._short_url(megathread_submission)
        logger.info(f"Posted megathread: {megathread_short_url}")

        # Phase 2: Post all episodes (without complete discussions table)
        for ep_num in range(start_episode, end_episode + 1):
            episode_number = str(ep_num)
            is_final = show.episode_count and ep_num >= show.episode_count

            title = self._build_title(show, episode_number, is_final)
            body = self._build_post_body(show, episode_number)

            submission = subreddit.submit(
                title=title,
                selftext=body,
                flair_id=self.templates.flair_id or None,
                flair_text=self.templates.flair_text or None,
            )
            short_url = self._short_url(submission)
            batch_episodes.append((ep_num, short_url, submission))
            logger.info(f"Posted episode {ep_num}: {short_url}")

        # Phase 3: Build complete list including megathread for discussions table
        # Megathread comes first, then individual episodes
        batch_episode_list = [(megathread_number, megathread_short_url)]
        batch_episode_list.extend([(str(ep_num), url) for ep_num, url, _ in batch_episodes])

        # Phase 4: Edit all batch episodes to include complete discussions table
        for ep_num, url, submission in batch_episodes:
            updated_body = self._build_post_body(
                show,
                str(ep_num),
                additional_episodes=batch_episode_list,
            )
            submission.edit(updated_body)
            logger.info(f"Updated episode {ep_num} with complete discussions table")

        # Phase 5: Edit megathread to include complete discussions table
        updated_megathread_body = self._build_megathread_body(
            show,
            start_episode,
            end_episode,
            additional_episodes=batch_episode_list,
        )
        megathread_submission.edit(updated_megathread_body)
        logger.info("Updated megathread with complete discussions table")

        # Phase 6: Update previous episode threads (up to MAX_EPISODES_TO_UPDATE)
        # Exclude all batch episodes and megathread from the update list
        batch_urls = {url for _, url, _ in batch_episodes}
        batch_urls.add(megathread_short_url)
        updated_count = self._update_previous_episodes_batch(
            show,
            batch_urls=batch_urls,
            batch_episodes=batch_episode_list,
        )

        return {
            "episodes": [(ep_num, url) for ep_num, url, _ in batch_episodes],
            "episodes_posted": len(batch_episodes),
            "megathread": (megathread_number, megathread_short_url),
            "updated_count": updated_count,
        }

    def _update_previous_episodes_batch(
        self,
        show,
        batch_urls: set,
        batch_episodes: List[Tuple[str, str]],
    ) -> int:
        """Update previous episode threads after a batch post.

        Args:
            show: Show model instance
            batch_urls: Set of URLs for newly posted episodes (to exclude)
            batch_episodes: List of (episode_number, url) for batch episodes

        Returns:
            Number of episodes successfully updated
        """
        return self._update_episode_threads(
            show,
            exclude_urls=batch_urls,
            additional_episodes=batch_episodes,
        )

    def update_existing_threads(self, show) -> int:
        """Update existing episode discussion threads with latest show info.

        Edits the last MAX_EPISODES_TO_UPDATE episodes to refresh streaming links,
        info links, discussions table, and aliases using current database values.

        Args:
            show: Show model instance

        Returns:
            Number of episodes successfully updated
        """
        return self._update_episode_threads(show)

    def _update_previous_episodes(
        self,
        show,
        new_episode_url: str,
        new_episode_number: str,
    ) -> int:
        """Update previous episode discussion threads with latest show info.

        Edits the last MAX_EPISODES_TO_UPDATE episodes (excluding the new one)
        to include updated show information and the complete discussions table.

        Args:
            show: Show model instance (refreshed from DB for latest data)
            new_episode_url: URL of the newly posted episode (to exclude from updates)
            new_episode_number: Episode number of the new episode (to include in discussions)

        Returns:
            Number of episodes successfully updated
        """
        return self._update_episode_threads(
            show,
            exclude_urls={new_episode_url},
            current_episode_url=new_episode_url,
            current_episode_number=new_episode_number,
        )

    def _update_episode_threads(
        self,
        show,
        exclude_urls: Optional[set] = None,
        current_episode_url: Optional[str] = None,
        current_episode_number: Optional[str] = None,
        additional_episodes: Optional[List[Tuple[str, str]]] = None,
    ) -> int:
        """Core method to update episode discussion threads.

        Args:
            show: Show model instance
            exclude_urls: Set of URLs to exclude from updates
            current_episode_url: URL of new episode to include in discussions
            current_episode_number: Episode number of new episode
            additional_episodes: List of (episode_number, url) for batch mode

        Returns:
            Number of episodes successfully updated
        """
        # Get episodes with discussion URLs, excluding removed episodes
        episodes_qs = (
            show.episodes.filter(discussion_url__isnull=False, scheduled_for_removal=False)
            .exclude(discussion_url="")
            .order_by("-order")
        )

        episodes = list(episodes_qs)

        # Filter out excluded URLs if any
        if exclude_urls:
            episodes = [ep for ep in episodes if ep.discussion_url not in exclude_urls]

        # Limit to MAX_EPISODES_TO_UPDATE
        episodes = episodes[:MAX_EPISODES_TO_UPDATE]

        updated_count = 0
        for episode in episodes:
            submission_id = self._extract_submission_id(episode.discussion_url)
            if not submission_id:
                logger.warning(f"Could not extract submission ID from {episode.discussion_url}")
                continue

            try:
                submission = self.reddit.submission(id=submission_id)
                updated_body = self._build_post_body(
                    show,
                    episode.number,
                    current_episode_url=current_episode_url,
                    current_episode_number=current_episode_number,
                    additional_episodes=additional_episodes,
                )
                submission.edit(updated_body)
                updated_count += 1
                logger.info(f"Updated episode {episode.number} thread: {episode.discussion_url}")
            except Exception as e:
                logger.error(f"Failed to update episode {episode.number}: {e}")

        return updated_count

    @staticmethod
    def _extract_submission_id(url: str) -> Optional[str]:
        """Extract Reddit submission ID from a discussion URL.

        Args:
            url: Reddit URL like https://www.reddit.com/r/anime/comments/abc123/...

        Returns:
            Submission ID (e.g., 'abc123') or None if not found
        """
        # Match reddit.com/r/subreddit/comments/ID/...
        match = re.search(r"reddit\.com/r/[^/]+/comments/([a-zA-Z0-9]+)", url)
        if match:
            return match.group(1)
        return None

    def _build_title(self, show, episode_number: str, is_final: bool) -> str:
        """Build the post title from templates."""
        # Choose title template based on whether English title exists
        if show.title_en:
            title = self.templates.title_with_en.format(
                show_name=show.title,
                show_name_en=show.title_en,
                episode=episode_number,
            )
        else:
            title = self.templates.title.format(
                show_name=show.title,
                episode=episode_number,
            )

        # Add final episode postfix if applicable
        if is_final and self.templates.title_postfix_final:
            title += " " + self.templates.title_postfix_final

        return title

    def _build_megathread_title(self, show, start_episode: int, end_episode: int) -> str:
        """Build the megathread title from templates."""
        if show.title_en and self.templates.batch_thread_title_with_en:
            title = self.templates.batch_thread_title_with_en.format(
                show_name=show.title,
                show_name_en=show.title_en,
                start_episode=start_episode,
                episode=end_episode,
            )
        else:
            title = self.templates.batch_thread_title.format(
                show_name=show.title,
                start_episode=start_episode,
                episode=end_episode,
            )
        return title

    def _build_megathread_body(
        self,
        show,
        start_episode: int,
        end_episode: int,
        additional_episodes: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """Build the megathread body from templates.

        Args:
            show: Show model instance
            start_episode: First episode number in the batch
            end_episode: Last episode number in the batch
            additional_episodes: List of (episode_number, url) for discussions table
        """
        body = self.templates.batch_thread_body

        # Format streams section
        streams = self._format_streams(show)

        # Format info links section
        links = self._format_links(show)

        # Format discussions section
        discussions = self._format_discussions(
            show,
            additional_episodes=additional_episodes,
        )

        # Format aliases
        aliases = self._format_aliases(show)

        # Replace placeholders
        body = body.format(
            show_name=show.title,
            show_name_en=show.title_en or show.title,
            start_episode=start_episode,
            episode=end_episode,
            aliases=aliases,
            streams=streams,
            links=links,
            discussions=discussions,
        )

        return body

    def _build_post_body(
        self,
        show,
        episode_number: str,
        current_episode_url: Optional[str] = None,
        current_episode_number: Optional[str] = None,
        additional_episodes: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """Build the post body from templates.

        Args:
            show: Show model instance
            episode_number: Episode number for the post
            current_episode_url: URL of the current post (for self-inclusion in discussions)
            current_episode_number: Episode number of current post (for discussions table)
            additional_episodes: List of (episode_number, url) tuples for batch posts
        """
        body = self.templates.body

        # Format streams section
        streams = self._format_streams(show)

        # Format info links section
        links = self._format_links(show)

        # Format discussions section (include current/additional episodes if provided)
        discussions = self._format_discussions(
            show,
            current_episode_url=current_episode_url,
            current_episode_number=current_episode_number,
            additional_episodes=additional_episodes,
        )

        # Format aliases
        aliases = self._format_aliases(show)

        # Replace placeholders
        body = body.format(
            show_name=show.title,
            show_name_en=show.title_en or show.title,
            episode=episode_number,
            episode_alt_number="",  # Not implemented yet
            episode_name="",  # Not implemented yet
            aliases=aliases,
            poll="",  # Not implemented yet
            spoiler=self._format_spoiler(show),
            streams=streams,
            links=links,
            discussions=discussions,
        )

        return body

    def _format_streams(self, show) -> str:
        """Format streaming links for the post body."""
        stream_links = show.links.filter(link_type__category="stream").select_related("link_type")

        if not stream_links:
            return "*None*"

        format_template = self.templates.formats.get("stream", "* [{service_name}]({stream_link})")
        lines = []
        for link in stream_links:
            lines.append(format_template.format(
                service_name=link.link_type.name,
                stream_link=link.url,
            ))
        return "\n".join(lines)

    def _format_links(self, show) -> str:
        """Format information links for the post body."""
        info_links = show.links.filter(link_type__category="info").select_related("link_type")

        if not info_links:
            return "*None*"

        format_template = self.templates.formats.get("link", "* [{site_name}]({link})")
        lines = []
        for link in info_links:
            # For subreddit links, use the subreddit path as the display name
            if link.link_type.slug == "subreddit":
                site_name = link.url  # e.g., "/r/OshiNoKo"
                # Ensure URL is a full Reddit URL
                if link.url.startswith("/r/"):
                    url = f"https://www.reddit.com{link.url}"
                else:
                    url = link.url
            else:
                site_name = link.link_type.name
                url = link.url

            lines.append(format_template.format(
                site_name=site_name,
                link=url,
            ))
        return "\n".join(lines)

    def _format_discussions(
        self,
        show,
        current_episode_url: Optional[str] = None,
        current_episode_number: Optional[str] = None,
        additional_episodes: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """Format episode discussions for the post body.

        Args:
            show: Show model instance
            current_episode_url: URL of current episode to include in table
            current_episode_number: Episode number of current episode
            additional_episodes: List of (episode_number, url) tuples for batch posts
        """
        episodes = list(
            show.episodes.filter(discussion_url__isnull=False, scheduled_for_removal=False)
            .exclude(discussion_url="")
            .order_by("order")
        )

        # Check if we have any episodes (existing, current, or additional)
        has_episodes = (
            bool(episodes)
            or (current_episode_url and current_episode_number)
            or additional_episodes
        )

        if not has_episodes:
            return self.templates.formats.get("discussion_none", "*No discussions yet!*")

        # Build table header
        header = self.templates.formats.get("discussion_header", "Episode|Link|Score")
        align = self.templates.formats.get("discussion_align", ":-:|:-:|:-:")
        #  TODO: handle poll links and scores
        row_template = self.templates.formats.get("discussion", "{episode}|[Link]({link})|[{score}]({poll_link})")

        lines = [header, align]

        # Add existing episodes from database
        for ep in episodes:
            lines.append(row_template.format(
                episode=ep.number,
                link=ep.discussion_url,
                score="-",  # Score not implemented yet
                poll_link="",  # Poll not implemented yet
            ))

        # Add current episode if provided (single post mode)
        if current_episode_url and current_episode_number:
            lines.append(row_template.format(
                episode=current_episode_number,
                link=current_episode_url,
                score="-",
                poll_link="",
            ))

        # Add additional episodes if provided (batch mode)
        if additional_episodes:
            for ep_number, ep_url in additional_episodes:
                lines.append(row_template.format(
                    episode=ep_number,
                    link=ep_url,
                    score="-",
                    poll_link="",
                ))

        return "\n".join(lines)

    def _format_aliases(self, show) -> str:
        """Format show aliases for the post body."""
        if not show.aliases:
            return ""

        format_template = self.templates.formats.get("aliases", "Alternative names: *{aliases}*")
        # Join aliases that are stored one per line
        aliases_list = [a.strip() for a in show.aliases.split("\n") if a.strip()]
        if not aliases_list:
            return ""

        return format_template.format(aliases=", ".join(aliases_list))

    def _format_spoiler(self, show) -> str:
        """Format spoiler warning for the post body."""
        if show.has_source:
            return self.templates.formats.get(
                "spoiler",
                "**Reminder:** Please do not discuss plot points not yet seen or skipped in the show."
            )
        return ""

    def prepare_custom_episode_post(
        self,
        custom_show: dict,
        discussion_subject: str,
        is_final: bool = False,
    ) -> tuple:
        """Prepare a custom episode discussion post preview.

        Builds the title and body without posting to Reddit.

        Args:
            custom_show: Dictionary with show data
            discussion_subject: What appears before "discussion" (e.g., "Episode 1", "Movie")
            is_final: Whether this is the final episode

        Returns:
            tuple of (title, body)
        """
        title = self._build_custom_title(custom_show, discussion_subject, is_final)
        body = self._build_custom_post_body(custom_show, discussion_subject)
        return title, body

    def submit_custom_episode_post(
        self,
        custom_show: dict,
        discussion_subject: str,
        is_final: bool = False,
    ) -> dict:
        """Submit a custom episode discussion post to Reddit.

        Posts a standalone discussion thread without creating database records.

        Args:
            custom_show: Dictionary with show data:
                - show_name: Japanese title (required)
                - show_name_en: English title (optional)
                - aliases: List of alternative names (optional)
                - has_source: Whether has source material (optional)
                - streams: List of {name, url} dicts (optional)
                - info_links: List of {name, url} dicts (optional)
            discussion_subject: What appears before "discussion" (e.g., "Episode 1", "Movie")
            is_final: Whether this is the final episode

        Returns:
            dict with 'url' and 'id' of the posted submission
        """
        title = self._build_custom_title(custom_show, discussion_subject, is_final)
        body = self._build_custom_post_body(custom_show, discussion_subject)

        subreddit = self.reddit.subreddit(self.subreddit)

        # Submit the post
        submission = subreddit.submit(
            title=title,
            selftext=body,
            flair_id=self.templates.flair_id or None,
            flair_text=self.templates.flair_text or None,
        )

        return {
            "url": self._short_url(submission),
            "id": submission.id,
        }

    def _build_custom_title(
        self,
        custom_show: dict,
        discussion_subject: str,
        is_final: bool,
    ) -> str:
        """Build the post title for a custom episode."""
        show_name = custom_show.get("show_name", "")
        show_name_en = custom_show.get("show_name_en", "")

        # Build title directly with discussion_subject (e.g., "Episode 1 discussion", "Movie discussion")
        if show_name_en:
            title = f"{show_name} • {show_name_en} - {discussion_subject}"
        else:
            title = f"{show_name} - {discussion_subject}"

        if is_final and self.templates.title_postfix_final:
            title += " " + self.templates.title_postfix_final

        return title

    def _build_custom_post_body(self, custom_show: dict, discussion_subject: str) -> str:
        """Build the post body for a custom episode."""
        body = self.templates.body

        show_name = custom_show.get("show_name", "")
        show_name_en = custom_show.get("show_name_en", "") or show_name

        # Format streams section
        streams = self._format_custom_streams(custom_show.get("streams", []))

        # Format info links section
        links = self._format_custom_links(custom_show.get("info_links", []))

        # Format aliases
        aliases = self._format_custom_aliases(custom_show.get("aliases", []))

        # Format spoiler based on has_source
        spoiler = ""
        if custom_show.get("has_source", False):
            spoiler = self.templates.formats.get(
                "spoiler",
                "**Reminder:** Please do not discuss plot points not yet seen or skipped in the show."
            )

        # No discussions table for custom posts (standalone)
        discussions = self.templates.formats.get("discussion_none", "*No discussions yet!*")

        body = body.format(
            show_name=show_name,
            show_name_en=show_name_en,
            episode=discussion_subject,
            episode_alt_number="",
            episode_name="",
            aliases=aliases,
            poll="",
            spoiler=spoiler,
            streams=streams,
            links=links,
            discussions=discussions,
        )

        return body

    def _format_custom_streams(self, streams: list) -> str:
        """Format streaming links from a list of {name, url} dicts."""
        if not streams:
            return "*None*"

        format_template = self.templates.formats.get("stream", "* [{service_name}]({stream_link})")
        lines = []
        for stream in streams:
            if stream.get("name") and stream.get("url"):
                lines.append(format_template.format(
                    service_name=stream["name"],
                    stream_link=stream["url"],
                ))

        return "\n".join(lines) if lines else "*None*"

    def _format_custom_links(self, info_links: list) -> str:
        """Format information links from a list of {name, url, slug} dicts."""
        if not info_links:
            return "*None*"

        format_template = self.templates.formats.get("link", "* [{site_name}]({link})")
        lines = []
        for link in info_links:
            name = link.get("name", "")
            url = link.get("url", "")
            if name and url:
                # Subreddit links are plain text, not a markdown link
                if link.get("slug") == "subreddit":
                    lines.append(f"* {url}")
                else:
                    lines.append(format_template.format(
                        site_name=name,
                        link=url,
                    ))

        return "\n".join(lines) if lines else "*None*"

    def _format_custom_aliases(self, aliases: list) -> str:
        """Format aliases from a list of strings."""
        if not aliases:
            return ""

        # Filter out empty strings
        aliases_list = [a.strip() for a in aliases if a.strip()]
        if not aliases_list:
            return ""

        format_template = self.templates.formats.get("aliases", "Alternative names: *{aliases}*")
        return format_template.format(aliases=", ".join(aliases_list))

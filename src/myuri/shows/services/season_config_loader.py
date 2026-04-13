"""
Season Config Loader Service

Parses YAML season config files and imports shows into the database.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from shows.models import Season, Show, LinkType, ShowLink

logger = logging.getLogger(__name__)

# Link type mappings
# Info category
INFO_LINK_TYPES = {
    "mal": ("mal", "MyAnimeList"),
    "anilist": ("anilist", "AniList"),
    "anidb": ("anidb", "AniDB"),
    "kitsu": ("kitsu", "Kitsu"),
    "animeplanet": ("animeplanet", "Anime-Planet"),
    "official": ("official", "Official Site"),
    "subreddit": ("subreddit", "Subreddit"),
}

# Stream category
STREAM_LINK_TYPES = {
    "crunchyroll": ("crunchyroll", "Crunchyroll"),
    "hidive": ("hidive", "HIDIVE"),
    "funimation": ("funimation", "Funimation"),
    "netflix": ("netflix", "Netflix"),
    "disney": ("disney", "Disney+"),
    "hulu": ("hulu", "Hulu"),
    "youtube": ("youtube", "YouTube"),
    "museasia": ("museasia", "Muse Asia"),
    "nyaa": ("nyaa", "Nyaa"),
    "wakanim": ("wakanim", "Wakanim"),
    "animelab": ("animelab", "AnimeLab"),
    "vrv": ("vrv", "VRV"),
    "anione": ("anione", "Ani-One"),
    "oceanveil": ("oceanveil", "Oceanveil"),
}

# Season name mapping
SEASON_MAP = {
    "1": "winter",
    "2": "spring",
    "3": "summer",
    "4": "fall",
    "winter": "winter",
    "spring": "spring",
    "summer": "summer",
    "fall": "fall",
}


@dataclass
class ImportStats:
    """Statistics from an import operation."""
    shows_created: int = 0
    shows_updated: int = 0
    links_created: int = 0
    links_updated: int = 0
    errors: list = field(default_factory=list)

    @property
    def total_shows(self) -> int:
        return self.shows_created + self.shows_updated


def parse_season_from_filename(filename: str) -> tuple[int, str]:
    """
    Extract year and season from filename.

    Expected format: YYYY_N_season.yaml (e.g., 2026_1_winter.yaml)

    Args:
        filename: The filename to parse

    Returns:
        Tuple of (year, season_code) where season_code is 'winter', 'spring', etc.

    Raises:
        ValueError: If filename doesn't match expected format
    """
    # Remove extension and path
    basename = Path(filename).stem

    # Try pattern: YYYY_N_season (e.g., 2026_1_winter)
    match = re.match(r"(\d{4})_(\d)_(\w+)", basename)
    if match:
        year = int(match.group(1))
        season_num = match.group(2)
        season_name = match.group(3).lower()

        # Use season name if valid, otherwise map from number
        if season_name in SEASON_MAP:
            season = SEASON_MAP[season_name]
        elif season_num in SEASON_MAP:
            season = SEASON_MAP[season_num]
        else:
            raise ValueError(f"Invalid season in filename: {basename}")

        return year, season

    # Try pattern: YYYY_season (e.g., 2026_winter)
    match = re.match(r"(\d{4})_(\w+)", basename)
    if match:
        year = int(match.group(1))
        season_name = match.group(2).lower()

        if season_name not in SEASON_MAP:
            raise ValueError(f"Invalid season in filename: {basename}")

        return year, SEASON_MAP[season_name]

    raise ValueError(f"Could not parse season from filename: {filename}")


def load_season_config(yaml_path: str) -> list[dict]:
    """
    Load and parse a multi-document YAML file.

    Args:
        yaml_path: Path to the YAML file

    Returns:
        List of show dictionaries parsed from the YAML
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse multi-document YAML
    docs = list(yaml.safe_load_all(content))

    # Filter out None documents (from empty sections or comments)
    return [doc for doc in docs if doc is not None]


def get_or_create_link_type(slug: str, name: str, category: str) -> LinkType:
    """
    Get or create a LinkType by slug.

    Args:
        slug: URL-friendly identifier
        name: Display name
        category: 'info' or 'stream'

    Returns:
        The LinkType instance
    """
    link_type, created = LinkType.objects.get_or_create(
        slug=slug,
        defaults={"name": name, "category": category}
    )

    # Update name if it changed
    if not created and link_type.name != name:
        link_type.name = name
        link_type.save()

    return link_type


def parse_link_key(key: str) -> tuple[str, Optional[str]]:
    """
    Parse a link key that may contain a display name.

    Format: 'key' or 'key|DisplayName'

    Args:
        key: The YAML key to parse

    Returns:
        Tuple of (slug, display_name) where display_name is None if not provided
    """
    if "|" in key:
        parts = key.split("|", 1)
        return parts[0].lower(), parts[1]
    return key.lower(), None


def import_shows_to_database(
    yaml_path: str,
    dry_run: bool = False
) -> ImportStats:
    """
    Import shows from a YAML file into the database.

    Args:
        yaml_path: Path to the YAML file
        dry_run: If True, don't actually save to database

    Returns:
        ImportStats with counts and any errors
    """
    stats = ImportStats()

    # Parse season from filename
    try:
        year, season_code = parse_season_from_filename(yaml_path)
    except ValueError as e:
        stats.errors.append(str(e))
        return stats

    # Load YAML documents
    try:
        show_docs = load_season_config(yaml_path)
    except Exception as e:
        stats.errors.append(f"Failed to parse YAML: {e}")
        return stats

    if dry_run:
        logger.info(f"[DRY RUN] Would import {len(show_docs)} shows to {season_code.title()} {year}")
        stats.shows_created = len(show_docs)
        return stats

    # Get or create the season
    season, _ = Season.objects.get_or_create(
        year=year,
        season=season_code
    )

    # Process each show document
    for doc in show_docs:
        try:
            _import_single_show(doc, season, stats)
        except Exception as e:
            title = doc.get("title", "Unknown")
            error_msg = f"Error importing '{title}': {e}"
            logger.exception(error_msg)
            stats.errors.append(error_msg)

    logger.info(
        f"Import complete: {stats.shows_created} created, {stats.shows_updated} updated, "
        f"{stats.links_created} links created, {stats.links_updated} links updated"
    )

    return stats


def _import_single_show(doc: dict, season: Season, stats: ImportStats) -> None:
    """Import a single show document."""
    title = doc.get("title", "").strip()
    if not title:
        stats.errors.append("Skipped document with empty title")
        return

    title_en = doc.get("title_en", "").strip()
    has_source = doc.get("has_source", False)

    # Parse aliases
    aliases_list = doc.get("alias", [])
    if isinstance(aliases_list, list):
        # Filter out empty strings and join with newlines
        aliases = "\n".join(a.strip() for a in aliases_list if a and a.strip())
    else:
        aliases = ""

    # Try to find existing show by title within the season
    show, created = Show.objects.get_or_create(
        title=title,
        season=season,
        defaults={
            "title_en": title_en,
            "aliases": aliases,
            "has_source": has_source,
            "enabled": True,
        }
    )

    if created:
        stats.shows_created += 1
    else:
        # Update existing show
        show.title_en = title_en
        show.aliases = aliases
        show.has_source = has_source
        show.save()
        stats.shows_updated += 1

    # Process info links
    info_section = doc.get("info", {})
    if info_section:
        _process_links(show, info_section, "info", stats)

    # Process stream links
    streams_section = doc.get("streams", {})
    if streams_section:
        _process_links(show, streams_section, "stream", stats)


def _process_links(
    show: Show,
    links_dict: dict,
    category: str,
    stats: ImportStats
) -> None:
    """Process and save links for a show."""
    link_type_map = INFO_LINK_TYPES if category == "info" else STREAM_LINK_TYPES

    for key, url in links_dict.items():
        # Skip empty URLs
        if not url or not url.strip():
            continue

        url = url.strip()

        # Parse key (may have display name like 'funimation|Funimation')
        slug, custom_name = parse_link_key(key)

        # Get link type info
        if slug in link_type_map:
            default_slug, default_name = link_type_map[slug]
        else:
            # Unknown link type - create it dynamically
            default_slug = slug
            default_name = custom_name or slug.title()

        # Use custom name if provided
        name = custom_name or default_name

        # Get or create the link type
        link_type = get_or_create_link_type(default_slug, name, category)

        # Create or update the show link
        show_link, created = ShowLink.objects.get_or_create(
            show=show,
            link_type=link_type,
            defaults={"url": url}
        )

        if created:
            stats.links_created += 1
        elif show_link.url != url:
            show_link.url = url
            show_link.save()
            stats.links_updated += 1


def get_season_config_files(config_dir: str) -> list[dict]:
    """
    Get list of available season config files.

    Args:
        config_dir: Directory to scan for YAML files

    Returns:
        List of dicts with 'filename', 'path', 'year', 'season' keys
    """
    files = []
    config_path = Path(config_dir)

    if not config_path.exists():
        return files

    for yaml_file in sorted(config_path.glob("*.yaml"), reverse=True):
        try:
            year, season = parse_season_from_filename(yaml_file.name)
            files.append({
                "filename": yaml_file.name,
                "path": str(yaml_file),
                "year": year,
                "season": season,
                "display": f"{season.title()} {year}",
            })
        except ValueError:
            # Skip files that don't match the expected pattern
            continue

    return files


def delete_season_shows(year: int, season_code: str) -> int:
    """
    Delete all shows and their episodes for a season.

    Args:
        year: The year
        season_code: The season code ('winter', 'spring', etc.)

    Returns:
        Number of shows deleted
    """
    try:
        season = Season.objects.get(year=year, season=season_code)
    except Season.DoesNotExist:
        return 0

    count = season.shows.count()
    # Cascade delete will handle episodes and links
    season.shows.all().delete()

    return count

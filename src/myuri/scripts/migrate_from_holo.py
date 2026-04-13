"""
Migration script to import shows and episodes from an existing Holo database.

Usage:
    cd src/myuri
    python manage.py shell < scripts/migrate_from_holo.py

Or run directly (will set up Django environment):
    cd src/myuri
    python scripts/migrate_from_holo.py

Source database location:
    scripts/temp/database.sqlite (configurable via SOURCE_DB_PATH)
"""

import os
import sys
import sqlite3
from pathlib import Path

# Set up Django environment if running directly
if __name__ == "__main__":
    # Add the myuri directory to path
    script_dir = Path(__file__).resolve().parent
    myuri_dir = script_dir.parent
    sys.path.insert(0, str(myuri_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django
    django.setup()

from django.db import transaction
from shows.models import Show, Episode, Season

# Configuration
SOURCE_DB_PATH = Path(__file__).resolve().parent / "temp" / "database.sqlite"
TARGET_SEASON_YEAR = 2025
TARGET_SEASON_NAME = "fall"


def get_source_connection(db_path: Path) -> sqlite3.Connection:
    """Connect to the source SQLite database."""
    if not db_path.exists():
        raise FileNotFoundError(f"Source database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_or_create_season(year: int, season_name: str) -> Season:
    """Get or create the target season for imported shows."""
    season, created = Season.objects.get_or_create(
        year=year,
        season=season_name
    )
    if created:
        print(f"Created new season: {season}")
    else:
        print(f"Using existing season: {season}")
    return season


def fetch_shows(conn: sqlite3.Connection) -> list:
    """Fetch all shows from the source database."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, name_en, length, has_source
        FROM Shows
    """)
    return cursor.fetchall()


def fetch_aliases(conn: sqlite3.Connection, show_id: int) -> list:
    """Fetch aliases for a show from the source database."""
    cursor = conn.cursor()
    cursor.execute("SELECT alias FROM Aliases WHERE show = ?", (show_id,))
    return [row["alias"] for row in cursor.fetchall()]


def fetch_episodes(conn: sqlite3.Connection) -> list:
    """Fetch all episodes from the source database."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT show, episode, post_url
        FROM Episodes
    """)
    return cursor.fetchall()


def migrate_shows(conn: sqlite3.Connection, season: Season) -> dict:
    """
    Migrate shows from source database to Django.

    Returns a mapping of old_show_id -> new_show instance.
    """
    shows = fetch_shows(conn)
    id_mapping = {}
    imported_count = 0
    skipped_count = 0

    print(f"\nMigrating {len(shows)} shows...")

    for row in shows:
        old_id = row["id"]
        title = row["name"]
        title_en = row["name_en"] or ""
        episode_count = row["length"]
        has_source = bool(row["has_source"])

        # Check if show already exists by title
        existing = Show.objects.filter(title=title).first()
        if existing:
            print(f"  SKIP: '{title}' already exists (id={existing.id})")
            id_mapping[old_id] = existing
            skipped_count += 1
            continue

        # Get aliases
        aliases = fetch_aliases(conn, old_id)
        aliases_text = "\n".join(aliases) if aliases else ""

        # Create new show with enabled=False
        new_show = Show.objects.create(
            title=title,
            title_en=title_en,
            aliases=aliases_text,
            has_source=has_source,
            enabled=False,  # All imports disabled per requirements
            episode_count=episode_count,
            season=season
        )

        id_mapping[old_id] = new_show
        imported_count += 1
        alias_info = f" ({len(aliases)} aliases)" if aliases else ""
        print(f"  OK: '{title}'{alias_info}")

    print(f"\nShows: {imported_count} imported, {skipped_count} skipped")
    return id_mapping


def migrate_episodes(conn: sqlite3.Connection, id_mapping: dict) -> tuple:
    """
    Migrate episodes from source database to Django.

    Returns (imported_count, skipped_count).
    """
    episodes = fetch_episodes(conn)
    imported_count = 0
    skipped_count = 0
    missing_show_count = 0

    print(f"\nMigrating {len(episodes)} episodes...")

    for row in episodes:
        old_show_id = row["show"]
        episode_num = row["episode"]
        post_url = row["post_url"] or ""

        # Look up new show from mapping
        new_show = id_mapping.get(old_show_id)
        if not new_show:
            missing_show_count += 1
            continue

        # Check if episode already exists
        existing = Episode.objects.filter(
            show=new_show,
            number=str(episode_num)
        ).first()

        if existing:
            skipped_count += 1
            continue

        # Create new episode
        Episode.objects.create(
            show=new_show,
            number=str(episode_num),
            order=episode_num,
            discussion_url=post_url,
            is_special=False,
            scheduled_for_removal=False
        )
        imported_count += 1

    print(f"Episodes: {imported_count} imported, {skipped_count} skipped")
    if missing_show_count > 0:
        print(f"  ({missing_show_count} episodes had missing shows)")

    return imported_count, skipped_count


def main():
    """Main migration function."""
    print("=" * 60)
    print("Holo Database Migration Script")
    print("=" * 60)

    # Check source database
    print(f"\nSource database: {SOURCE_DB_PATH}")
    if not SOURCE_DB_PATH.exists():
        print(f"ERROR: Source database not found!")
        print(f"Please place the Holo database at: {SOURCE_DB_PATH}")
        sys.exit(1)

    try:
        conn = get_source_connection(SOURCE_DB_PATH)
        print("Connected to source database.")
    except Exception as e:
        print(f"ERROR: Failed to connect to source database: {e}")
        sys.exit(1)

    try:
        # Use atomic transaction for rollback on error
        with transaction.atomic():
            # Get or create target season
            season = get_or_create_season(TARGET_SEASON_YEAR, TARGET_SEASON_NAME)

            # Migrate shows
            id_mapping = migrate_shows(conn, season)

            # Migrate episodes
            migrate_episodes(conn, id_mapping)

            print("\n" + "=" * 60)
            print("Migration completed successfully!")
            print("=" * 60)
            print("\nNext steps:")
            print("1. Check imported shows in Django admin (all are disabled)")
            print("2. Enable shows you want to track")
            print("3. Verify episode discussion URLs are correct")

    except Exception as e:
        print(f"\nERROR: Migration failed: {e}")
        print("Transaction rolled back - no changes made.")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()

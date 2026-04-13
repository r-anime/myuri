# Scripts

Management scripts for the myuri project.

## migrate_from_holo.py

Imports shows and episodes from an existing Holo database into Django.

### Prerequisites

1. Place the source Holo SQLite database at:
   ```
   scripts/temp/database.sqlite
   ```

2. Ensure Django migrations are up to date:
   ```bash
   cd src/myuri
   python manage.py migrate
   ```

### Usage

```bash
cd src/myuri
python scripts/migrate_from_holo.py
```

Or via Django shell:
```bash
cd src/myuri
python manage.py shell < scripts/migrate_from_holo.py
```

### Configuration

Edit the constants at the top of the script to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `SOURCE_DB_PATH` | `scripts/temp/database.sqlite` | Path to Holo database |
| `TARGET_SEASON_YEAR` | `2025` | Year for imported shows |
| `TARGET_SEASON_NAME` | `"fall"` | Season (winter/spring/summer/fall) |


### What it does

- Imports shows from Holo's `Shows` table
- Imports aliases from Holo's `Aliases` table (joined into `Show.aliases`)
- Imports episodes from Holo's `Episodes` table with discussion URLs
- All imported shows are set to `enabled=False`
- Skips shows/episodes that already exist (safe to re-run)
- Uses atomic transactions (rolls back on any error)

### Field Mapping

**Shows:**

| Holo | Django |
|------|--------|
| `name` | `Show.title` |
| `name_en` | `Show.title_en` |
| `length` | `Show.episode_count` |
| `has_source` | `Show.has_source` |


**Episodes:**

| Holo | Django |
|------|--------|
| `episode` | `Episode.number` (converted to string) |
| `episode` | `Episode.order` |
| `post_url` | `Episode.discussion_url` |

### After Migration

1. Check imported shows in Django admin (`/admin/shows/show/`)
2. All shows are disabled by default - enable the ones you want to track
3. Verify episode discussion URLs are correct

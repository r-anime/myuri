"""Bulk import of episodes from pasted CSV text (used by the Show admin)."""
import csv
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from shows.models import Episode

HEADER_NAMES = {"episode_id", "episode", "number"}
NUMBER_MAX_LENGTH = Episode._meta.get_field("number").max_length


@dataclass
class EpisodeRow:
    number: str
    order: int
    discussion_url: str = ""


class EpisodeCsvError(Exception):
    """Raised when pasted CSV text is invalid; carries one message per bad line."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_episode_csv(text: str) -> list[EpisodeRow]:
    """
    Parse "episode_id,order,discussion_url" lines into rows.

    Columns may be separated by commas or tabs (so spreadsheet cells can be
    pasted directly). Blank lines and an optional header line are ignored, and
    discussion_url may be left empty.
    """
    delimiter = "\t" if "\t" in text else ","
    validate_url = URLValidator()
    rows: list[EpisodeRow] = []
    errors: list[str] = []
    seen: set[str] = set()

    for line_no, cells in enumerate(csv.reader(text.splitlines(), delimiter=delimiter), start=1):
        cells = [cell.strip() for cell in cells]
        if not any(cells):
            continue
        if not rows and not errors and cells[0].lower() in HEADER_NAMES:
            continue
        if len(cells) not in (2, 3):
            errors.append(f"Line {line_no}: expected episode_id, order, discussion_url (got {len(cells)} columns)")
            continue

        number, order = cells[0], cells[1]
        url = cells[2] if len(cells) == 3 else ""

        if not number:
            errors.append(f"Line {line_no}: episode_id is empty")
            continue
        if len(number) > NUMBER_MAX_LENGTH:
            errors.append(f"Line {line_no}: episode_id '{number}' is longer than {NUMBER_MAX_LENGTH} characters")
            continue
        if number in seen:
            errors.append(f"Line {line_no}: episode_id '{number}' appears more than once")
            continue
        try:
            order = int(order)
        except ValueError:
            errors.append(f"Line {line_no}: order '{order}' is not a whole number")
            continue
        if url:
            try:
                validate_url(url)
            except ValidationError:
                errors.append(f"Line {line_no}: '{url}' is not a valid URL")
                continue

        seen.add(number)
        rows.append(EpisodeRow(number=number, order=order, discussion_url=url))

    if errors:
        raise EpisodeCsvError(errors)
    return rows


@transaction.atomic
def import_episodes(show, rows: list[EpisodeRow]) -> tuple[int, int]:
    """
    Create or update the show's episodes from parsed rows.

    Episodes are matched on number; an existing episode gets its order and
    discussion_url overwritten. Returns (created_count, updated_count).
    """
    created = updated = 0
    for row in rows:
        episode = show.episodes.filter(number=row.number).first()
        if episode is None:
            show.episodes.create(
                number=row.number,
                order=row.order,
                discussion_url=row.discussion_url,
            )
            created += 1
        else:
            episode.order = row.order
            episode.discussion_url = row.discussion_url
            episode.save(update_fields=["order", "discussion_url", "updated_at"])
            updated += 1
    return created, updated

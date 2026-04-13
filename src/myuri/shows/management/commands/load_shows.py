import yaml
from django.core.management.base import BaseCommand, CommandError
from shows.models import Franchise, Season, Show, LinkType, Episode, ShowLink


class Command(BaseCommand):
    help = "Load anime shows data from a YAML file"

    def add_arguments(self, parser):
        parser.add_argument("yaml_file", type=str, help="Path to the YAML file")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data before loading",
        )

    def handle(self, *args, **options):
        yaml_file = options["yaml_file"]

        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {yaml_file}")
        except yaml.YAMLError as e:
            raise CommandError(f"Invalid YAML: {e}")

        if options["clear"]:
            self.stdout.write("Clearing existing data...")
            Episode.objects.all().delete()
            ShowLink.objects.all().delete()
            Show.objects.all().delete()
            Season.objects.all().delete()
            Franchise.objects.all().delete()
            LinkType.objects.all().delete()

        # Load link types
        for lt_data in data.get("link_types", []):
            lt, created = LinkType.objects.update_or_create(
                slug=lt_data["slug"],
                defaults={
                    "name": lt_data["name"],
                    "category": lt_data["category"],
                    "display_order": lt_data.get("display_order", 0),
                },
            )
            status = "Created" if created else "Updated"
            self.stdout.write(f"  {status} link type: {lt.name}")

        # Load franchises
        franchises = {}
        for fr_data in data.get("franchises", []):
            fr, created = Franchise.objects.update_or_create(
                name=fr_data["name"],
            )
            franchises[fr_data["name"]] = fr
            status = "Created" if created else "Updated"
            self.stdout.write(f"  {status} franchise: {fr.name}")

        # Load seasons
        seasons = {}
        for s_data in data.get("seasons", []):
            season, created = Season.objects.update_or_create(
                year=s_data["year"],
                season=s_data["season"],
            )
            seasons[(s_data["year"], s_data["season"])] = season
            status = "Created" if created else "Updated"
            self.stdout.write(f"  {status} season: {season}")

        # Load shows
        for show_data in data.get("shows", []):
            # Get or create season
            season_key = (show_data["season"]["year"], show_data["season"]["season"])
            if season_key not in seasons:
                season, _ = Season.objects.get_or_create(
                    year=season_key[0],
                    season=season_key[1],
                )
                seasons[season_key] = season
            season = seasons[season_key]

            # Get franchise if specified
            franchise = None
            if "franchise" in show_data:
                franchise = franchises.get(show_data["franchise"])
                if not franchise:
                    franchise, _ = Franchise.objects.get_or_create(
                        name=show_data["franchise"]
                    )
                    franchises[show_data["franchise"]] = franchise

            # Create or update show
            show, created = Show.objects.update_or_create(
                title=show_data["title"],
                season=season,
                defaults={
                    "title_en": show_data.get("title_en", ""),
                    "aliases": "\n".join(show_data.get("aliases", [])),
                    "has_source": show_data.get("has_source", False),
                    "enabled": show_data.get("enabled", True),
                    "franchise": franchise,
                },
            )
            status = "Created" if created else "Updated"
            self.stdout.write(f"  {status} show: {show.title}")

            # Load links
            for link_data in show_data.get("links", []):
                try:
                    link_type = LinkType.objects.get(slug=link_data["type"])
                    ShowLink.objects.update_or_create(
                        show=show,
                        link_type=link_type,
                        defaults={"url": link_data["url"]},
                    )
                    self.stdout.write(f"    Added link: {link_type.name}")
                except LinkType.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    Skipped link: unknown type '{link_data['type']}'"
                        )
                    )

            # Load episodes
            for idx, ep_data in enumerate(show_data.get("episodes", []), start=1):
                # Use explicit order if provided, otherwise use position in list
                order = ep_data.get("order", idx * 10)
                Episode.objects.update_or_create(
                    show=show,
                    number=str(ep_data["number"]),
                    defaults={
                        "order": order,
                        "air_date": ep_data.get("air_date"),
                        "is_special": ep_data.get("is_special", False),
                        "discussion_url": ep_data.get("discussion_url", ""),
                    },
                )
                self.stdout.write(f"    Added episode: {ep_data['number']} (order: {order})")

        self.stdout.write(self.style.SUCCESS("Data loaded successfully!"))

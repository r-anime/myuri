import functools
import json
import logging
import os
from collections import defaultdict

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST


def admin_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')
        if not request.user.is_staff:
            return render(request, 'no_permission.html', {'username': request.user.username})
        return view_func(request, *args, **kwargs)
    return wrapper

from .models import Show, Episode, Season, LinkType, ShowLink

logger = logging.getLogger(__name__)

_SEASON_ORDER = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}


@admin_required
def home(request):
    """Homepage showing enabled shows and recent episodes."""
    enabled_shows = (
        Show.objects.filter(enabled=True)
        .select_related("season", "franchise")
        .annotate(current_episode_count=Count("episodes", filter=Q(episodes__scheduled_for_removal=False)))
    )

    # Get the 10 most recent episodes by air date
    recent_episodes = (
        Episode.objects
        .filter(air_date__isnull=False)
        .select_related("show", "show__season")
        .order_by("-air_date")[:10]
    )

    return render(request, "shows/home.html", {
        "shows": enabled_shows,
        "recent_episodes": recent_episodes,
    })


@admin_required
def shows_list(request, show_id=None):
    """Shows management page with sidebar and show details."""
    shows_qs = Show.objects.all().select_related("season", "franchise")

    # Get search query
    search_query = request.GET.get("q", "")
    if search_query:
        shows_qs = shows_qs.filter(title__icontains=search_query)

    # Get selected show
    selected_show = None
    episodes = []
    last_active_episode = None
    if show_id:
        selected_show = get_object_or_404(Show, id=show_id)
        episodes = selected_show.episodes.all().order_by("order")
        last_active_episode = selected_show.episodes.filter(scheduled_for_removal=False).order_by("-order").first()
    else:
        # Default to first enabled show if none selected, falling back to any show
        selected_show = shows_qs.filter(enabled=True).first() or shows_qs.first()
        if selected_show:
            episodes = selected_show.episodes.all().order_by("order")
            last_active_episode = selected_show.episodes.filter(scheduled_for_removal=False).order_by("-order").first()

    latest_date_map = {
        row['show_id']: row['latest_air']
        for row in Episode.objects
            .filter(show__in=shows_qs, discussion_url__gt='', air_date__isnull=False)
            .values('show_id')
            .annotate(latest_air=Max('air_date'))
    }

    now = timezone.now()
    season_map = defaultdict(list)
    for show in shows_qs:
        latest = latest_date_map.get(show.id)
        if latest is None:
            show.status_color = 'grey'
        else:
            days_ago = (now - latest).days
            if days_ago < 7:
                show.status_color = 'green'
            elif days_ago < 14:
                show.status_color = 'orange'
            else:
                show.status_color = 'red'
        season_map[show.season].append(show)

    seasons_with_shows = sorted(
        season_map.items(),
        key=lambda x: (x[0].year, _SEASON_ORDER[x[0].season]),
        reverse=True,
    )

    show_links = []
    link_types_json = "[]"
    aliases_list = []
    if selected_show:
        show_links = list(
            selected_show.links.select_related("link_type")
            .order_by("link_type__display_order", "link_type__name")
        )
        link_types_json = json.dumps([{"id": lt.id, "name": lt.name} for lt in LinkType.objects.all()])
        aliases_list = [a.strip() for a in selected_show.aliases.splitlines() if a.strip()]

    all_seasons = list(Season.objects.all())
    seasons_json = json.dumps([{"id": s.id, "label": str(s)} for s in all_seasons])

    return render(request, "shows/shows_list.html", {
        "shows": shows_qs,
        "seasons_with_shows": seasons_with_shows,
        "selected_show": selected_show,
        "episodes": episodes,
        "last_active_episode": last_active_episode,
        "search_query": search_query,
        "show_links": show_links,
        "link_types_json": link_types_json,
        "seasons_json": seasons_json,
        "aliases_list": aliases_list,
    })


@admin_required
@require_POST
def fire_next_episode(request, show_id):
    """Fire a new episode discussion post to Reddit.

    Creates the next episode for the show and posts a discussion thread to Reddit.
    """
    show = get_object_or_404(Show, id=show_id)

    # Calculate next episode number (max order + 1), excluding removed episodes
    last_episode = show.episodes.filter(scheduled_for_removal=False).order_by("-order").first()
    if last_episode:
        next_order = last_episode.order + 1
        # Try to parse the episode number as int, otherwise increment
        try:
            next_number = str(int(last_episode.number) + 1)
        except ValueError:
            next_number = str(next_order)
    else:
        next_order = 1
        next_number = "1"

    # Check if this is the final episode
    is_final = False
    if show.episode_count:
        try:
            is_final = int(next_number) >= show.episode_count
        except ValueError:
            pass  # Can't determine if final for non-numeric episodes

    try:
        # Import RedditService lazily to avoid requiring praw at module load
        from .services import RedditService

        # Post to Reddit
        reddit_service = RedditService()
        result = reddit_service.submit_episode_post(show, next_number, is_final)

        # Create Episode record with discussion URL
        episode = Episode.objects.create(
            show=show,
            number=next_number,
            order=next_order,
            air_date=timezone.now(),
            discussion_url=result["url"],
        )

        logger.info(
            f"Posted episode {next_number} for {show.title}: {result['url']} "
            f"(updated {result['updated_count']} previous episodes)"
        )

        # Send notification
        from .services import NotificationService
        notification_service = NotificationService()
        notification_service.notify_episode_posted(
            show_title=show.title,
            episode=next_number,
            url=result["url"],
            user=request.user.username if request.user.is_authenticated else None,
        )

        return JsonResponse({
            "success": True,
            "episode_number": next_number,
            "discussion_url": result["url"],
            "is_final": is_final,
            "updated_count": result["updated_count"],
        })

    except FileNotFoundError as e:
        logger.error(f"Config error: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)

    except Exception as e:
        logger.exception(f"Error posting episode for {show.title}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def fire_episode_batch(request, show_id):
    """Fire a batch of episode discussion posts to Reddit.

    Posts multiple episodes at once and then edits all of them to include
    the complete discussions table.
    """
    show = get_object_or_404(Show, id=show_id)

    try:
        data = json.loads(request.body)
        start_episode = int(data.get("start_episode"))
        end_episode = int(data.get("end_episode"))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return JsonResponse({
            "success": False,
            "error": "Invalid request data",
        }, status=400)

    # Validate range
    if start_episode > end_episode:
        return JsonResponse({
            "success": False,
            "error": "Start episode must be less than or equal to end episode",
        }, status=400)

    if end_episode - start_episode + 1 > 100:
        return JsonResponse({
            "success": False,
            "error": "Maximum 100 episodes can be posted at once",
        }, status=400)

    try:
        # Import RedditService lazily to avoid requiring praw at module load
        from .services import RedditService

        reddit_service = RedditService()
        result = reddit_service.submit_episode_batch(
            show,
            start_episode,
            end_episode,
        )

        # Create Episode records for megathread and all posted episodes
        last_episode = show.episodes.filter(scheduled_for_removal=False).order_by("-order").first()
        base_order = last_episode.order + 1 if last_episode else 1

        # Create megathread Episode record first (order before episodes)
        megathread_number, megathread_url = result["megathread"]
        Episode.objects.create(
            show=show,
            number=megathread_number,
            order=base_order,
            air_date=timezone.now(),
            discussion_url=megathread_url,
            is_special=True,  # Mark megathread as special
        )

        # Create Episode records for individual episodes (order after megathread)
        for i, (ep_num, url) in enumerate(result["episodes"]):
            Episode.objects.create(
                show=show,
                number=str(ep_num),
                order=base_order + 1 + i,
                air_date=timezone.now(),
                discussion_url=url,
            )

        logger.info(
            f"Posted megathread and episodes {start_episode}-{end_episode} for {show.title} "
            f"({result['episodes_posted']} episodes, updated {result['updated_count']} previous)"
        )

        return JsonResponse({
            "success": True,
            "start_episode": start_episode,
            "end_episode": end_episode,
            "episodes_posted": result["episodes_posted"],
            "megathread_url": megathread_url,
            "updated_count": result["updated_count"],
        })

    except FileNotFoundError as e:
        logger.error(f"Config error: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)

    except Exception as e:
        logger.exception(f"Error posting episode batch for {show.title}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def batch_update_threads(request, show_id):
    """Update existing episode discussion threads with latest show info.

    Edits up to 24 most recent episode threads to refresh streaming links,
    info links, discussions table, and aliases.
    """
    show = get_object_or_404(Show, id=show_id)

    try:
        # Import RedditService lazily to avoid requiring praw at module load
        from .services import RedditService

        reddit_service = RedditService()
        updated_count = reddit_service.update_existing_threads(show)

        logger.info(f"Batch updated {updated_count} threads for {show.title}")

        return JsonResponse({
            "success": True,
            "updated_count": updated_count,
        })

    except FileNotFoundError as e:
        logger.error(f"Config error: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)

    except Exception as e:
        logger.exception(f"Error batch updating threads for {show.title}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
def season_config_manage(request):
    """Manage season config imports from YAML files."""
    from .services import (
        get_season_config_files,
        import_shows_to_database,
        delete_season_shows,
        parse_season_from_filename,
    )

    # Get config directory path (relative to src/)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_dir = os.path.join(base_dir, "season_configs")

    # Get available config files
    config_files = get_season_config_files(config_dir)

    # Get existing seasons with show counts
    existing_seasons = (
        Season.objects
        .annotate(
            show_count=Count("shows"),
            active_show_count=Count("shows", filter=Q(shows__enabled=True))
        )
        .order_by("-year", "season")
    )

    import_result = None
    delete_result = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "import":
            selected_file = request.POST.get("config_file")
            if selected_file:
                file_path = os.path.join(config_dir, selected_file)
                if os.path.exists(file_path):
                    try:
                        stats = import_shows_to_database(file_path)
                        import_result = {
                            "success": True,
                            "created": stats.shows_created,
                            "updated": stats.shows_updated,
                            "links_created": stats.links_created,
                            "links_updated": stats.links_updated,
                            "errors": stats.errors,
                        }
                        if stats.errors:
                            messages.warning(
                                request,
                                f"Imported with {len(stats.errors)} error(s)"
                            )
                        else:
                            messages.success(
                                request,
                                f"Imported {stats.shows_created} new shows, "
                                f"updated {stats.shows_updated} existing shows"
                            )
                    except Exception as e:
                        logger.exception("Error importing season config")
                        import_result = {
                            "success": False,
                            "error": str(e),
                        }
                        messages.error(request, f"Import failed: {e}")
                else:
                    messages.error(request, "Selected file not found")
            else:
                messages.error(request, "No file selected")

        elif action == "delete_season":
            year = request.POST.get("year")
            season_code = request.POST.get("season")
            if year and season_code:
                try:
                    count = delete_season_shows(int(year), season_code)
                    delete_result = {
                        "success": True,
                        "deleted": count,
                    }
                    messages.success(
                        request,
                        f"Deleted {count} shows from {season_code.title()} {year}"
                    )
                except Exception as e:
                    logger.exception("Error deleting season shows")
                    delete_result = {
                        "success": False,
                        "error": str(e),
                    }
                    messages.error(request, f"Delete failed: {e}")
            else:
                messages.error(request, "Invalid season specified")

        # Redirect to avoid form resubmission
        return redirect("shows:season_config")

    return render(request, "shows/season_config.html", {
        "config_files": config_files,
        "existing_seasons": existing_seasons,
        "import_result": import_result,
        "delete_result": delete_result,
    })


@admin_required
def custom_episode(request):
    """Render the custom episode posting form."""
    # Get link types for dropdowns, grouped by category
    link_types = LinkType.objects.all().order_by("category", "display_order", "name")

    # Build JSON data for JavaScript
    link_types_data = {
        "info": [],
        "stream": [],
    }
    for lt in link_types:
        link_types_data[lt.category].append({
            "id": lt.id,
            "name": lt.name,
            "slug": lt.slug,
        })

    return render(request, "shows/custom_episode.html", {
        "link_types_json": json.dumps(link_types_data),
    })


@admin_required
@require_POST
def prepare_custom_episode(request):
    """Prepare a custom episode discussion post preview.

    Returns the title and body that would be posted, without actually posting.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON data",
        }, status=400)

    # Validate required fields
    show_name = data.get("show_name", "").strip()
    discussion_subject = data.get("discussion_subject", "").strip()

    if not show_name:
        return JsonResponse({
            "success": False,
            "error": "Show name is required",
        }, status=400)

    if not discussion_subject:
        return JsonResponse({
            "success": False,
            "error": "Discussion subject is required",
        }, status=400)

    # Build custom show data
    custom_show = {
        "show_name": show_name,
        "show_name_en": data.get("show_name_en", "").strip(),
        "aliases": data.get("aliases", []),
        "has_source": data.get("has_source", False),
        "streams": data.get("streams", []),
        "info_links": data.get("info_links", []),
    }

    is_final = data.get("is_final", False)

    try:
        from .services import RedditService

        reddit_service = RedditService()
        title, body = reddit_service.prepare_custom_episode_post(
            custom_show,
            discussion_subject,
            is_final,
        )

        return JsonResponse({
            "success": True,
            "title": title,
            "body": body,
        })

    except FileNotFoundError as e:
        logger.error(f"Config error: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)

    except Exception as e:
        logger.exception(f"Error preparing custom episode for {show_name}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
def scan_page(request):
    """Render the scan page for detecting new anime episode releases."""
    from datetime import timedelta
    from .models import SchedulerConfig, ScanHistory

    # Load last scan results from session
    last_scan_data = request.session.get("last_scan_result")
    last_scan_result = None

    if last_scan_data:
        from .services import ScanResult
        try:
            last_scan_result = ScanResult.from_dict(last_scan_data)
        except Exception as e:
            logger.warning(f"Failed to load scan results from session: {e}")

    # Get scheduler config
    scheduler_config = SchedulerConfig.get_config()

    # Get the most recent scan from database
    latest_db_scan = ScanHistory.objects.first()  # Already ordered by -scan_time

    # Check if scheduler process is actually running
    scheduler_running = False
    scheduler_last_heartbeat = None
    try:
        from django_apscheduler.models import DjangoJob, DjangoJobExecution

        # Check if our job is registered
        job = DjangoJob.objects.filter(id="scheduled_scan").first()
        if job:
            # Check the most recent execution
            last_execution = DjangoJobExecution.objects.filter(
                job=job
            ).order_by("-run_time").first()

            if last_execution:
                scheduler_last_heartbeat = last_execution.run_time
                # Consider running if executed within 2x the interval (with 1 min buffer)
                threshold = timedelta(minutes=(scheduler_config.interval_minutes * 2) + 1)
                if timezone.now() - last_execution.run_time < threshold:
                    scheduler_running = True
            else:
                # Job exists but hasn't run yet - scheduler just started
                scheduler_running = True
                scheduler_last_heartbeat = job.next_run_time
    except Exception as e:
        logger.warning(f"Failed to check scheduler status: {e}")

    enabled_shows = Show.objects.filter(enabled=True).order_by("title")

    return render(request, "shows/scan.html", {
        "last_scan_result": last_scan_result,
        "scheduler_config": scheduler_config,
        "latest_db_scan": latest_db_scan,
        "scheduler_running": scheduler_running,
        "scheduler_last_heartbeat": scheduler_last_heartbeat,
        "enabled_shows": enabled_shows,
    })


@admin_required
@require_POST
def trigger_scan(request):
    """Trigger a scan for new episodes from Nyaa.si and Crunchyroll."""
    from .services import NyaaScanner, CrunchyrollScanner
    from .services.scan_result import ScanResult

    # Get enabled shows
    enabled_shows = Show.objects.filter(enabled=True)

    if not enabled_shows.exists():
        return JsonResponse({
            "success": False,
            "error": "No enabled shows found",
        }, status=400)

    try:
        nyaa_result = NyaaScanner().scan_recent(enabled_shows)
        cr_result   = CrunchyrollScanner().scan_recent(enabled_shows)

        result = ScanResult(
            scan_time=nyaa_result.scan_time,
            episodes_found=nyaa_result.episodes_found + cr_result.episodes_found,
            shows_scanned=nyaa_result.shows_scanned,
            errors=nyaa_result.errors + cr_result.errors,
        )

        # Store results in session
        request.session["last_scan_result"] = result.to_dict()

        logger.info(
            f"Scan completed: {len(result.episodes_found)} episodes found "
            f"across {result.shows_scanned} shows"
        )

        return JsonResponse({
            "success": True,
            **result.to_dict(),
        })

    except Exception as e:
        logger.exception("Error during scan")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def scan_individual_show(request, show_id):
    """Scan Nyaa for a single show using NyaaSpecificScanner.

    Returns episodes found for that show without touching the session, so
    the frontend can call this per-show and accumulate results itself.
    """
    from .services.nyaa_specific import NyaaSpecificScanner

    show = get_object_or_404(Show, id=show_id, enabled=True)

    try:
        scanner = NyaaSpecificScanner()
        result = scanner.scan_show(show, max_age_days=7)

        return JsonResponse({
            "success": True,
            "show_id": show.id,
            "show_title": show.title,
            "episodes_found": result.to_dict()["episodes_found"],
            "errors": result.errors,
        })

    except Exception as e:
        logger.exception(f"Error scanning individual show {show.title}")
        return JsonResponse({
            "success": False,
            "show_id": show.id,
            "show_title": show.title,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def store_scan_results(request):
    """Store a combined set of scan results in the session.

    Called by the frontend after all per-show scans complete so the
    existing eligibility-check and auto-post flows can operate on the
    accumulated results.
    """
    from datetime import datetime
    from .services.scan_result import ScanResult, FoundEpisode

    try:
        data = json.loads(request.body)

        result = ScanResult(
            scan_time=datetime.now(),
            shows_scanned=data.get("shows_scanned", 0),
            errors=data.get("errors", []),
            episodes_found=[
                FoundEpisode(
                    show_id=ep["show_id"],
                    show_title=ep["show_title"],
                    episode_number=ep["episode_number"],
                    source=ep["source"],
                    source_title=ep["source_title"],
                    found_at=datetime.fromisoformat(ep["found_at"]),
                    link=ep["link"],
                )
                for ep in data.get("episodes_found", [])
            ],
        )

        request.session["last_scan_result"] = result.to_dict()

        return JsonResponse({
            "success": True,
            "scan_time": result.scan_time.isoformat(),
        })

    except Exception as e:
        logger.exception("Error storing scan results")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def trigger_scan_individual(request):
    """Trigger a targeted per-show scan using NyaaSpecificScanner.

    Loops through every enabled show and issues a dedicated Nyaa search
    for each one, then merges all results into a single ScanResult stored
    in the session (same shape as trigger_scan).
    """
    from datetime import datetime
    from .services import NyaaSpecificScanner
    from .services.scan_result import ScanResult

    enabled_shows = list(Show.objects.filter(enabled=True))

    if not enabled_shows:
        return JsonResponse({
            "success": False,
            "error": "No enabled shows found",
        }, status=400)

    try:
        scanner = NyaaSpecificScanner()
        combined = ScanResult(scan_time=datetime.now(), shows_scanned=0)

        for show in enabled_shows:
            result = scanner.scan_show(show)
            combined.episodes_found.extend(result.episodes_found)
            combined.errors.extend(result.errors)
            combined.shows_scanned += 1

        request.session["last_scan_result"] = combined.to_dict()

        logger.info(
            f"Individual scan completed: {len(combined.episodes_found)} episodes found "
            f"across {combined.shows_scanned} shows"
        )

        return JsonResponse({
            "success": True,
            **combined.to_dict(),
        })

    except Exception as e:
        logger.exception("Error during individual scan")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def clear_scan_results(request):
    """Clear the last manual scan results from session."""
    if "last_scan_result" in request.session:
        del request.session["last_scan_result"]

    return JsonResponse({"success": True})


@admin_required
@require_POST
def auto_post_episodes(request):
    """Post all eligible episodes from the last scan to Reddit.

    Compares scan results to database and posts episodes that are:
    - Episode 1 for shows with no existing episodes
    - Exactly latest_episode + 1 for shows with existing episodes
    """
    from .services import ScanResult, AutoPostService
    from dataclasses import asdict

    # Get scan results from session
    last_scan_data = request.session.get("last_scan_result")
    if not last_scan_data:
        return JsonResponse({
            "success": False,
            "error": "No scan results found. Please scan first.",
        }, status=400)

    try:
        scan_result = ScanResult.from_dict(last_scan_data)
        service = AutoPostService()

        # Determine eligibility and post
        eligibilities = service.determine_eligibility(scan_result)
        result = service.post_eligible_episodes(eligibilities)

        logger.info(
            f"Auto-post completed: {len(result.posted)} posted, "
            f"{len(result.skipped)} skipped, {len(result.failed)} failed"
        )

        return JsonResponse({
            "success": True,
            "posted": result.posted,
            "skipped": result.skipped,
            "failed": result.failed,
        })

    except Exception as e:
        logger.exception("Error during auto-post")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def check_eligibility(request):
    """Check which scanned episodes are eligible for auto-posting.

    Returns eligibility status for each found episode without posting anything.
    """
    from .services import ScanResult, AutoPostService
    from dataclasses import asdict

    # Get scan results from session
    last_scan_data = request.session.get("last_scan_result")
    if not last_scan_data:
        return JsonResponse({
            "success": False,
            "error": "No scan results found. Please scan first.",
        }, status=400)

    try:
        scan_result = ScanResult.from_dict(last_scan_data)
        service = AutoPostService()
        eligibilities = service.determine_eligibility(scan_result)

        return JsonResponse({
            "success": True,
            "eligibilities": [asdict(e) for e in eligibilities],
        })

    except Exception as e:
        logger.exception("Error checking eligibility")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
def wiki_export(request):
    """Generate Reddit wiki-formatted markdown for a season's shows."""
    seasons = Season.objects.all()
    selected_season = None
    wiki_markdown = ""

    season_id = request.GET.get("season_id")
    if season_id:
        try:
            selected_season = Season.objects.get(id=season_id)
            shows = Show.objects.filter(season=selected_season).order_by("title")
            wiki_markdown = generate_wiki_markdown(shows)
        except Season.DoesNotExist:
            pass

    return render(request, "shows/wiki_export.html", {
        "seasons": seasons,
        "selected_season": selected_season,
        "wiki_markdown": wiki_markdown,
    })


def generate_wiki_markdown(shows):
    """Generate Reddit wiki-formatted markdown for a list of shows.

    Format:
    **Japanese Title** (English Title)

    Ep. 1|Ep. 2|...|Ep. N
    :--:|:--:|...|:--:
    [Link](url)|[Link]()|...|[Link]()
    """
    blocks = []

    for show in shows:
        # Build title line
        if show.title_en:
            title_line = f"**{show.title}** ({show.title_en})"
        else:
            title_line = f"**{show.title}**"

        # Determine episode count (default to 12)
        episode_count = show.episode_count or 12

        # Build episode header row
        ep_headers = [f"Ep. {i}" for i in range(1, episode_count + 1)]
        header_row = "|".join(ep_headers)

        # Build alignment row
        alignment_row = "|".join([":--:"] * episode_count)

        # Build links row - map episodes to their discussion URLs (excluding removed)
        episode_urls = {}
        for ep in show.episodes.filter(scheduled_for_removal=False):
            try:
                ep_num = int(ep.number)
                if ep.discussion_url:
                    episode_urls[ep_num] = ep.discussion_url
            except ValueError:
                pass  # Skip non-numeric episodes like OVA

        links = []
        for i in range(1, episode_count + 1):
            url = episode_urls.get(i, "")
            links.append(f"[Link]({url})")
        links_row = "|".join(links)

        # Combine into block
        block = f"{title_line}\n\n{header_row}\n{alignment_row}\n{links_row}"
        blocks.append(block)

    return "\n\n".join(blocks)


@admin_required
@require_POST
def fire_custom_episode(request):
    """Fire a custom episode discussion post to Reddit.

    Accepts JSON body with show data and posts to Reddit without creating
    database records.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON data",
        }, status=400)

    # Validate required fields
    show_name = data.get("show_name", "").strip()
    discussion_subject = data.get("discussion_subject", "").strip()

    if not show_name:
        return JsonResponse({
            "success": False,
            "error": "Show name is required",
        }, status=400)

    if not discussion_subject:
        return JsonResponse({
            "success": False,
            "error": "Discussion subject is required",
        }, status=400)

    # Build custom show data
    custom_show = {
        "show_name": show_name,
        "show_name_en": data.get("show_name_en", "").strip(),
        "aliases": data.get("aliases", []),
        "has_source": data.get("has_source", False),
        "streams": data.get("streams", []),
        "info_links": data.get("info_links", []),
    }

    is_final = data.get("is_final", False)

    try:
        from .services import RedditService

        reddit_service = RedditService()
        result = reddit_service.submit_custom_episode_post(
            custom_show,
            discussion_subject,
            is_final,
        )

        logger.info(
            f"Posted custom '{discussion_subject}' for {show_name}: {result['url']}"
        )

        # Send notification
        from .services import NotificationService
        notification_service = NotificationService()
        notification_service.notify_custom_episode_posted(
            show_title=show_name,
            discussion_subject=discussion_subject,
            url=result["url"],
            user=request.user.username if request.user.is_authenticated else None,
        )

        return JsonResponse({
            "success": True,
            "discussion_subject": discussion_subject,
            "discussion_url": result["url"],
            "is_final": is_final,
        })

    except FileNotFoundError as e:
        logger.error(f"Config error: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)

    except Exception as e:
        logger.exception(f"Error posting custom episode for {show_name}")
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=500)


@admin_required
@require_POST
def mark_episode_for_removal(request, episode_id):
    """Mark an episode for removal and remove its thread from Reddit.

    Uses the Reddit moderator service to remove the discussion thread,
    then marks the episode as scheduled_for_removal.
    """
    episode = get_object_or_404(Episode, id=episode_id)

    # Check if already removed
    if episode.scheduled_for_removal:
        return JsonResponse({
            "success": False,
            "error": "Episode is already marked as removed",
        }, status=400)

    # Get the moderator service
    from .services import RedditModeratorService
    mod_service = RedditModeratorService()

    # Check if moderator functionality is available
    if not mod_service.is_available():
        return JsonResponse({
            "success": False,
            "error": "Moderator functionality not configured",
        }, status=503)

    # If episode has a discussion URL, remove it from Reddit
    if episode.discussion_url:
        result = mod_service.remove_thread(episode.discussion_url)

        if not result["success"]:
            logger.error(
                f"Failed to remove thread for {episode.show.title} episode {episode.number}: "
                f"{result['message']}"
            )
            return JsonResponse({
                "success": False,
                "error": f"Failed to remove thread from Reddit: {result['message']}",
            }, status=500)

        logger.info(
            f"Removed Reddit thread for {episode.show.title} episode {episode.number}: "
            f"{result['submission_id']}"
        )

    # Mark episode as removed
    episode.scheduled_for_removal = True
    episode.save()

    logger.info(f"Marked episode {episode.id} ({episode.show.title} - {episode.number}) for removal")

    # Send notification
    from .services import NotificationService
    notification_service = NotificationService()
    notification_service.notify_episode_removed(
        show_title=episode.show.title,
        episode=episode.number,
        url=episode.discussion_url or None,
        user=request.user.username if request.user.is_authenticated else None,
    )

    return JsonResponse({
        "success": True,
        "episode_id": episode.id,
        "show_title": episode.show.title,
        "episode_number": episode.number,
    })


@admin_required
@require_POST
def add_show_link(request, show_id):
    """Add a ShowLink for the given show."""
    show = get_object_or_404(Show, id=show_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    link_type_id = data.get("link_type_id")
    url = data.get("url", "").strip()
    if not link_type_id or not url:
        return JsonResponse({"success": False, "error": "link_type_id and url are required"}, status=400)

    link_type = get_object_or_404(LinkType, id=link_type_id)
    if ShowLink.objects.filter(show=show, link_type=link_type).exists():
        return JsonResponse({"success": False, "error": f"{link_type.name} link already exists for this show"}, status=400)

    link = ShowLink.objects.create(show=show, link_type=link_type, url=url)
    return JsonResponse({
        "success": True,
        "link": {
            "id": link.id,
            "link_type_id": link_type.id,
            "link_type_name": link_type.name,
            "url": link.url,
        },
    })


@admin_required
@require_POST
def update_show_link(request, show_id, link_id):
    """Update the URL of a ShowLink."""
    link = get_object_or_404(ShowLink, id=link_id, show_id=show_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    url = data.get("url", "").strip()
    if not url:
        return JsonResponse({"success": False, "error": "url is required"}, status=400)

    link.url = url
    link.save()
    return JsonResponse({"success": True})


@admin_required
@require_POST
def delete_show_link(request, show_id, link_id):
    """Delete a ShowLink."""
    link = get_object_or_404(ShowLink, id=link_id, show_id=show_id)
    link.delete()
    return JsonResponse({"success": True})


@admin_required
@require_POST
def update_show_season(request, show_id):
    """Update the season for a show."""
    show = get_object_or_404(Show, id=show_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    season_id = data.get("season_id")
    if not season_id:
        return JsonResponse({"success": False, "error": "season_id is required"}, status=400)

    season = get_object_or_404(Season, id=season_id)
    show.season = season
    show.save()
    return JsonResponse({"success": True, "season_str": str(season)})


@admin_required
@require_POST
def update_show_has_source(request, show_id):
    """Toggle the has_source flag for a show."""
    show = get_object_or_404(Show, id=show_id)
    show.has_source = not show.has_source
    show.save()
    return JsonResponse({"success": True, "has_source": show.has_source})


@admin_required
@require_POST
def update_show_enabled(request, show_id):
    """Toggle the enabled flag for a show."""
    show = get_object_or_404(Show, id=show_id)
    show.enabled = not show.enabled
    show.save()
    return JsonResponse({"success": True, "enabled": show.enabled})


@admin_required
@require_POST
def update_show_episode_count(request, show_id):
    """Update the episode count for a show."""
    show = get_object_or_404(Show, id=show_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    episode_count = data.get("episode_count")
    if episode_count is not None:
        try:
            episode_count = int(episode_count)
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "error": "episode_count must be a number or null"}, status=400)
        if episode_count < 1:
            return JsonResponse({"success": False, "error": "episode_count must be at least 1"}, status=400)

    show.episode_count = episode_count
    show.save()
    return JsonResponse({"success": True, "episode_count": show.episode_count})


@admin_required
@require_POST
def update_show_aliases(request, show_id):
    """Replace the alias list for a show."""
    show = get_object_or_404(Show, id=show_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    aliases = data.get("aliases")
    if not isinstance(aliases, list):
        return JsonResponse({"success": False, "error": "aliases must be a list"}, status=400)

    cleaned_aliases = [a.strip() for a in aliases if isinstance(a, str) and a.strip()]
    show.aliases = "\n".join(cleaned_aliases)
    show.save()
    return JsonResponse({"success": True, "aliases": cleaned_aliases})

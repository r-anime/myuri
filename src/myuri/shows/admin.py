from django.contrib import admin
from .models import (
    Franchise, Season, Show, LinkType, ShowLink, Episode,
    SchedulerConfig, ScanHistory, ScanEpisode, NotificationConfig
)


class ShowLinkInline(admin.TabularInline):
    model = ShowLink
    extra = 1


class EpisodeInline(admin.TabularInline):
    model = Episode
    extra = 1
    fields = ["number", "order", "air_date", "is_special", "discussion_url", "scheduled_for_removal"]
    ordering = ["order"]


@admin.register(Franchise)
class FranchiseAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["__str__", "year", "season"]
    list_filter = ["season", "year"]
    ordering = ["-year", "season"]


@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    list_display = ["title", "title_en", "season", "franchise", "episode_count", "enabled", "has_source", "batch_release"]
    list_filter = ["enabled", "season", "franchise", "has_source", "batch_release"]
    search_fields = ["title", "title_en", "aliases"]
    inlines = [ShowLinkInline, EpisodeInline]
    fieldsets = [
        (None, {
            "fields": ["title", "title_en", "aliases"]
        }),
        ("Classification", {
            "fields": ["season", "franchise", "episode_count", "has_source", "batch_release", "enabled"]
        }),
    ]


@admin.register(LinkType)
class LinkTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "category", "display_order"]
    list_filter = ["category"]
    prepopulated_fields = {"slug": ["name"]}
    ordering = ["display_order", "name"]


@admin.register(ShowLink)
class ShowLinkAdmin(admin.ModelAdmin):
    list_display = ["show", "link_type", "url"]
    list_filter = ["link_type"]
    search_fields = ["show__title", "show__title_en"]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ["show", "number", "order", "air_date", "is_special", "scheduled_for_removal"]
    list_filter = ["show", "is_special", "scheduled_for_removal"]
    search_fields = ["show__title"]
    ordering = ["show", "order"]


@admin.register(SchedulerConfig)
class SchedulerConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "enabled", "interval_minutes", "last_run"]
    readonly_fields = ["last_run"]

    def has_add_permission(self, request):
        # Only allow one instance (singleton)
        return not SchedulerConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the config
        return False


class ScanEpisodeInline(admin.TabularInline):
    model = ScanEpisode
    extra = 0
    readonly_fields = [
        "show", "episode_number", "source", "torrent_title",
        "link", "found_at", "status", "status_reason", "discussion_url"
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ScanHistory)
class ScanHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "scan_time", "trigger_type", "shows_scanned",
        "episodes_found", "episodes_posted", "episodes_skipped",
        "episodes_failed", "completed"
    ]
    list_filter = ["trigger_type", "completed"]
    readonly_fields = [
        "scan_time", "trigger_type", "shows_scanned",
        "episodes_found", "episodes_posted", "episodes_skipped",
        "episodes_failed", "errors", "completed"
    ]
    inlines = [ScanEpisodeInline]
    ordering = ["-scan_time"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ScanEpisode)
class ScanEpisodeAdmin(admin.ModelAdmin):
    list_display = [
        "scan", "show", "episode_number", "status",
        "source", "found_at"
    ]
    list_filter = ["status", "source", "scan"]
    search_fields = ["show__title", "torrent_title"]
    readonly_fields = [
        "scan", "show", "episode_number", "source", "torrent_title",
        "link", "found_at", "status", "status_reason", "discussion_url"
    ]
    ordering = ["-scan__scan_time"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotificationConfig)
class NotificationConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "discord_enabled"]

    def has_add_permission(self, request):
        # Only allow one instance (singleton)
        return not NotificationConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the config
        return False

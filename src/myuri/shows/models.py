from django.db import models


class Franchise(models.Model):
    """Groups related anime series (e.g., all Fate series)."""
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "franchises"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Season(models.Model):
    """Anime broadcast season (e.g., Winter 2026)."""
    SEASON_CHOICES = [
        ("winter", "Winter"),
        ("spring", "Spring"),
        ("summer", "Summer"),
        ("fall", "Fall"),
    ]

    year = models.IntegerField()
    season = models.CharField(max_length=10, choices=SEASON_CHOICES)

    class Meta:
        unique_together = ["year", "season"]
        ordering = ["-year", "season"]

    def __str__(self):
        return f"{self.get_season_display()} {self.year}"


class Show(models.Model):
    """Individual anime series."""
    title = models.CharField(max_length=200, help_text="Japanese title")
    title_en = models.CharField(
        max_length=200,
        blank=True,
        help_text="English title (optional)"
    )
    aliases = models.TextField(
        blank=True,
        help_text="Alternative titles, one per line"
    )
    has_source = models.BooleanField(
        default=False,
        help_text="Whether the anime has source material (manga, LN, etc.)"
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Whether the show is active (disable when completed)"
    )
    episode_count = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total number of episodes (if known)"
    )
    batch_release = models.BooleanField(
        default=False,
        help_text="Whether episodes are released in batches (e.g., Netflix)"
    )
    franchise = models.ForeignKey(
        Franchise,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shows"
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.PROTECT,
        related_name="shows"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        if self.title_en:
            return f"{self.title} ({self.title_en})"
        return self.title


class LinkType(models.Model):
    """Defines types of external links (extensible)."""
    CATEGORY_CHOICES = [
        ("info", "Information"),
        ("stream", "Streaming"),
    ]

    name = models.CharField(max_length=100, help_text="Display name (e.g., MyAnimeList)")
    slug = models.SlugField(unique=True, help_text="URL-friendly identifier (e.g., mal)")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    display_order = models.IntegerField(default=0, help_text="Order for display in UI")

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class ShowLink(models.Model):
    """Links a show to an external URL."""
    show = models.ForeignKey(
        Show,
        on_delete=models.CASCADE,
        related_name="links"
    )
    link_type = models.ForeignKey(
        LinkType,
        on_delete=models.PROTECT,
        related_name="show_links"
    )
    url = models.CharField(max_length=500)

    class Meta:
        unique_together = ["show", "link_type"]

    def __str__(self):
        return f"{self.show.title} - {self.link_type.name}"


class Episode(models.Model):
    """Individual episode of an anime series."""
    show = models.ForeignKey(
        Show,
        on_delete=models.CASCADE,
        related_name="episodes"
    )
    number = models.CharField(
        max_length=20,
        help_text="Episode number (allows OVA1, 0.5, etc.)"
    )
    order = models.IntegerField(
        default=0,
        help_text="Sort order (allows OVAs to be placed between episodes)"
    )
    air_date = models.DateTimeField(null=True, blank=True, help_text="Air date and time")
    is_special = models.BooleanField(
        default=False,
        help_text="For OVAs, specials, etc."
    )
    discussion_url = models.URLField(
        blank=True,
        help_text="Reddit discussion thread URL"
    )
    scheduled_for_removal = models.BooleanField(
        default=False,
        help_text="Whether this episode's thread has been removed from Reddit"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["show", "order"]

    def __str__(self):
        return f"{self.show.title} - Episode {self.number}"


class SchedulerConfig(models.Model):
    """Singleton configuration for the scheduled scanner."""
    enabled = models.BooleanField(
        default=False,
        help_text="Enable or disable scheduled scanning"
    )
    interval_minutes = models.IntegerField(
        default=2,
        help_text="Interval between scans in minutes"
    )
    last_run = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last scheduled scan"
    )

    class Meta:
        verbose_name = "Scheduler Configuration"
        verbose_name_plural = "Scheduler Configuration"

    def __str__(self):
        status = "Enabled" if self.enabled else "Disabled"
        return f"Scheduler ({status}, every {self.interval_minutes} min)"

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        """Get or create the singleton config instance."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class ScanHistory(models.Model):
    """History record for a scan operation."""
    TRIGGER_CHOICES = [
        ("scheduled", "Scheduled"),
        ("manual", "Manual"),
    ]

    scan_time = models.DateTimeField(auto_now_add=True)
    trigger_type = models.CharField(
        max_length=20,
        choices=TRIGGER_CHOICES,
        default="manual"
    )
    shows_scanned = models.IntegerField(default=0)
    episodes_found = models.IntegerField(default=0)
    episodes_posted = models.IntegerField(default=0)
    episodes_skipped = models.IntegerField(default=0)
    episodes_failed = models.IntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    completed = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Scan History"
        verbose_name_plural = "Scan Histories"
        ordering = ["-scan_time"]

    def __str__(self):
        return f"Scan at {self.scan_time:%Y-%m-%d %H:%M} ({self.trigger_type})"


class ScanEpisode(models.Model):
    """Episode found during a scan."""
    STATUS_CHOICES = [
        ("found", "Found"),
        ("eligible", "Eligible"),
        ("posted", "Posted"),
        ("skipped", "Skipped"),
        ("failed", "Failed"),
    ]

    scan = models.ForeignKey(
        ScanHistory,
        on_delete=models.CASCADE,
        related_name="scan_episodes"
    )
    show = models.ForeignKey(
        Show,
        on_delete=models.CASCADE,
        related_name="scan_episodes"
    )
    episode_number = models.CharField(max_length=20)
    source = models.CharField(max_length=50, default="Nyaa")
    source_title = models.CharField(max_length=500, blank=True)
    link = models.URLField(blank=True)
    found_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="found"
    )
    status_reason = models.CharField(
        max_length=200,
        blank=True,
        help_text="Reason for status (e.g., why skipped)"
    )
    discussion_url = models.URLField(
        blank=True,
        help_text="Reddit discussion URL if posted"
    )

    class Meta:
        verbose_name = "Scan Episode"
        verbose_name_plural = "Scan Episodes"
        ordering = ["-scan__scan_time", "show__title"]

    def __str__(self):
        return f"{self.show.title} Ep {self.episode_number} ({self.status})"


class NotificationConfig(models.Model):
    """Singleton configuration for notification services."""
    discord_enabled = models.BooleanField(
        default=False,
        help_text="Enable Discord webhook notifications"
    )

    class Meta:
        verbose_name = "Notification Configuration"
        verbose_name_plural = "Notification Configuration"

    def __str__(self):
        status = "Enabled" if self.discord_enabled else "Disabled"
        return f"Notification Config (Discord: {status})"

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        """Get or create the singleton config instance."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config

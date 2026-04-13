"""Management command to run the APScheduler for scheduled scanning."""
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util

logger = logging.getLogger(__name__)


@util.close_old_connections
def delete_old_job_executions(max_age=604_800):
    """
    Delete old job execution entries from the database.

    This helps prevent the database from filling up with old execution records.
    By default, keeps entries for the last 7 days (604800 seconds).
    """
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


@util.close_old_connections
def run_scheduled_scan_job():
    """Job function that runs the scheduled scan."""
    from shows.services import SchedulerService

    try:
        service = SchedulerService()
        service.run_scheduled_scan()
    except Exception as e:
        logger.exception(f"Scheduled scan failed: {e}")


class Command(BaseCommand):
    help = "Run the APScheduler for scheduled scanning of anime episodes."

    def handle(self, *args, **options):
        from shows.models import SchedulerConfig

        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

        # Get interval from config
        config = SchedulerConfig.get_config()
        interval_minutes = config.interval_minutes

        # Add the scan job
        scheduler.add_job(
            run_scheduled_scan_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="scheduled_scan",
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            f"Added scheduled scan job, running every {interval_minutes} minutes"
        )

        # Add daily cleanup job for old job executions
        scheduler.add_job(
            delete_old_job_executions,
            trigger=IntervalTrigger(days=1),
            id="delete_old_job_executions",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Added daily job execution cleanup")

        try:
            self.stdout.write(self.style.SUCCESS(
                f"Starting scheduler (scan every {interval_minutes} minutes)...\n"
                f"Press Ctrl+C to stop."
            ))
            scheduler.start()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopping scheduler..."))
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS("Scheduler stopped."))

"""Management command to manually run the delete_old_job_executions cleanup job."""
from django.core.management.base import BaseCommand

from shows.management.commands.runapscheduler import delete_old_job_executions


class Command(BaseCommand):
    help = "Delete old APScheduler job execution records (older than 7 days)."

    def handle(self, *args, **options):
        self.stdout.write("Running job execution cleanup...")
        delete_old_job_executions()
        self.stdout.write(self.style.SUCCESS("Done."))

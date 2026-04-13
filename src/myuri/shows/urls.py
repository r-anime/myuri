from django.urls import path
from . import views

app_name = "shows"

urlpatterns = [
    path("", views.home, name="home"),
    path("shows/", views.shows_list, name="shows_list"),
    path("shows/<int:show_id>/", views.shows_list, name="show_detail"),
    path("shows/<int:show_id>/fire-episode/", views.fire_next_episode, name="fire_episode"),
    path("shows/<int:show_id>/fire-episode-batch/", views.fire_episode_batch, name="fire_episode_batch"),
    path("shows/<int:show_id>/batch-update-threads/", views.batch_update_threads, name="batch_update_threads"),
    path("custom-episode/", views.custom_episode, name="custom_episode"),
    path("custom-episode/prepare/", views.prepare_custom_episode, name="prepare_custom_episode"),
    path("custom-episode/fire/", views.fire_custom_episode, name="fire_custom_episode"),
    path("season-config/", views.season_config_manage, name="season_config"),
    path("scan/", views.scan_page, name="scan"),
    path("wiki-export/", views.wiki_export, name="wiki_export"),
    path("scan/trigger/", views.trigger_scan, name="trigger_scan"),
    path("scan/trigger-individual/", views.trigger_scan_individual, name="trigger_scan_individual"),
    path("scan/show/<int:show_id>/", views.scan_individual_show, name="scan_individual_show"),
    path("scan/store-results/", views.store_scan_results, name="store_scan_results"),
    path("scan/clear/", views.clear_scan_results, name="clear_scan_results"),
    path("scan/check-eligibility/", views.check_eligibility, name="check_eligibility"),
    path("scan/auto-post/", views.auto_post_episodes, name="auto_post_episodes"),
    path("episode/<int:episode_id>/remove/", views.mark_episode_for_removal, name="mark_episode_removal"),
]

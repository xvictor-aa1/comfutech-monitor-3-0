# mantenimiento/urls.py
from django.urls import path
from . import views

app_name = "mantenimiento"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("backup/db/", views.backup_db, name="backup_db"),
    path("backup/configs/", views.backup_configs, name="backup_configs"),
    path("backup/full/", views.backup_full, name="backup_full"),
    path("backup/download/<str:filename>/", views.download_backup, name="download_backup"),
    path("backup/delete/<str:filename>/", views.delete_backup, name="delete_backup"),
    path("retention/apply/", views.apply_retention_now, name="apply_retention"),
]
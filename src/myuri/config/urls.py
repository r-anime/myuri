"""
URL configuration for myuri project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("", include("shows.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    # Serve static files (even when DEBUG=False); requires `manage.py collectstatic` to have run
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
]


def custom_404(request, exception):
    return render(request, "404.html", status=404)


handler404 = custom_404

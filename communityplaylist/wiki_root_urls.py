from django.urls import path, include

urlpatterns = [
    path('', include('wiki.urls', namespace='wiki')),
]

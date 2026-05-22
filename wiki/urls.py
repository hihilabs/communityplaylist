from django.urls import path
from . import views

app_name = 'wiki'

urlpatterns = [
    path('',                    views.token_list,   name='token_list'),
    path('api/search/',         views.api_search,   name='api_search'),
    path('api/yt/',             views.api_yt_search, name='api_yt_search'),
    path('token/<slug:slug>/',  views.token_detail, name='token_detail'),
    path('genre/<slug:slug>/',  views.genre_detail, name='genre_detail'),
]

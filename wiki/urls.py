from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'wiki'

urlpatterns = [
    path('',                    views.genre_orbital,   name='wiki_home'),
    path('tokens/',             views.token_list,      name='token_list'),
    path('graph/',              RedirectView.as_view(pattern_name='wiki:wiki_home', permanent=False), name='genre_graph'),
    path('tree/',               views.genre_tree,      name='genre_tree'),
    path('blob/',               RedirectView.as_view(pattern_name='wiki:wiki_home', permanent=False), name='genre_blob'),
    path('orbital/',            views.genre_orbital,   name='genre_orbital'),
    path('api/search/',         views.api_search,      name='api_search'),
    path('api/report/',         views.api_report,      name='api_report'),
    path('api/yt/',             views.api_yt_search,   name='api_yt_search'),
    path('api/graph/',          views.api_graph_data,  name='api_graph_data'),
    path('api/tree/',           views.api_tree_data,   name='api_tree_data'),
    path('token/<slug:slug>/',  views.token_detail,    name='token_detail'),
    path('genre/<slug:slug>/',  views.genre_detail,    name='genre_detail'),
]

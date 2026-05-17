from django.urls import path
from . import views

app_name = 'ops'

urlpatterns = [
    path('',                    views.panel,         name='panel'),
    path('cmd/',                views.run_cmd,        name='run_cmd'),
    path('ticket/create/',      views.create_ticket,  name='create_ticket'),
    path('ticket/<int:pk>/update/', views.update_ticket, name='update_ticket'),
]

from django.urls import path

from . import views

urlpatterns = [
    path("<int:order_id>/cart/", views.cart, name="cart"),
]

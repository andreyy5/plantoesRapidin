from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # URLs do plantão - ROTAS ESPECÍFICAS PRIMEIRO
    path('plantao/', include('apps.plantao.urls')),
    
    # URLs de usuários - APENAS SE NECESSÁRIO
    # path('usuarios/', include('apps.usuarios.urls')),
    
    # Redirecionamento da raiz - DEVE SER O ÚLTIMO
    path('', lambda request: redirect('dashboard')),
]
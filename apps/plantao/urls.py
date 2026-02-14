from django.urls import path
from . import views

urlpatterns = [
    # Dashboard - Acessível em /plantao/
    path('', views.dashboard, name='dashboard'),
    
    # Plantões - Acessível em /plantao/cadastrar/, /plantao/editar/, etc.
    path('cadastrar/', views.cadastrar_plantao, name='cadastrar_plantao'),
    path('editar/<int:plantao_id>/', views.editar_plantao, name='editar_plantao'),
    path('deletar/<int:plantao_id>/', views.deletar_plantao, name='deletar_plantao'),
    path('gerar-escala/', views.gerar_escala_automatica, name='gerar_escala'),
    
    # Colaboradores - Acessível em /plantao/colaboradores/
    path('colaboradores/', views.gerenciar_colaboradores, name='gerenciar_colaboradores'),
    path('colaboradores/cadastrar/', views.cadastrar_colaborador, name='cadastrar_colaborador'),
    path('colaboradores/editar/<int:colaborador_id>/', views.editar_colaborador, name='editar_colaborador'),
]
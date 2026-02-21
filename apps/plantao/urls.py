# Adicione estas URLs ao seu apps/plantao/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Plantões
    path('cadastrar/', views.cadastrar_plantao, name='cadastrar_plantao'),
    path('editar/<int:plantao_id>/', views.editar_plantao, name='editar_plantao'),
    path('deletar/<int:plantao_id>/', views.deletar_plantao, name='deletar_plantao'),
    path('gerar-escala/', views.gerar_escala_automatica, name='gerar_escala'),
    
    # Exportar PDF
    path('exportar-pdf/', views.exportar_pdf, name='exportar_pdf'),
    
    # Sistema de Trocas
    path('solicitar-troca/<int:plantao_id>/', views.solicitar_troca, name='solicitar_troca'),
    path('minhas-trocas/', views.minhas_trocas, name='minhas_trocas'),
    path('responder-troca/<int:troca_id>/<str:acao>/', views.responder_troca, name='responder_troca'),
    path('cancelar-troca/<int:troca_id>/', views.cancelar_troca, name='cancelar_troca'),
    
    # Notificações
    path('notificacoes/', views.notificacoes, name='notificacoes'),
    path('notificacao/<int:notif_id>/marcar-lida/', views.marcar_notificacao_lida, name='marcar_notificacao_lida'),
    
    # Colaboradores
    path('colaboradores/', views.gerenciar_colaboradores, name='gerenciar_colaboradores'),
    path('colaboradores/cadastrar/', views.cadastrar_colaborador, name='cadastrar_colaborador'),
    path('colaboradores/editar/<int:colaborador_id>/', views.editar_colaborador, name='editar_colaborador'),

     # ========== TÉCNICOS DE CAMPO ==========
    path('tecnicos/', views.dashboard_tecnicos, name='dashboard_tecnicos'),
    path('tecnicos/cadastrar/', views.cadastrar_plantao_tecnico, name='cadastrar_plantao_tecnico'),
    path('tecnicos/editar/<int:plantao_id>/', views.editar_plantao_tecnico, name='editar_plantao_tecnico'),
    path('tecnicos/deletar/<int:plantao_id>/', views.deletar_plantao_tecnico, name='deletar_plantao_tecnico'),
    path('tecnicos/gerar-escala/', views.gerar_escala_tecnicos, name='gerar_escala_tecnicos'),
    path('tecnicos/gerenciar/', views.gerenciar_tecnicos, name='gerenciar_tecnicos'),
    path('tecnicos/cadastrar-tecnico/', views.cadastrar_tecnico, name='cadastrar_tecnico'),
    path('tecnicos/editar-tecnico/<int:tecnico_id>/', views.editar_tecnico, name='editar_tecnico'),

]
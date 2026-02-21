from django.contrib import admin
from .models import Colaborador, Plantao, EscalaAutomatica, TrocaPlantao, Notificacao, TecnicoCampo, PlantaoTecnico, TrocaPlantaoTecnico, EscalaAutomaticaTecnico


@admin.register(Colaborador)
class ColaboradorAdmin(admin.ModelAdmin):
    list_display = ['ordem_fila', 'nome_completo', 'ativo', 'user']
    list_display_links = ['nome_completo']  # Define qual campo é o link
    list_filter = ['ativo']
    search_fields = ['nome_completo', 'user__username']
    ordering = ['ordem_fila']
    list_editable = ['ordem_fila', 'ativo']
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome_completo', 'ativo')
        }),
        ('Configurações de Fila', {
            'fields': ('ordem_fila',)
        }),
        ('Vínculo com Usuário', {
            'fields': ('user',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Plantao)
class PlantaoAdmin(admin.ModelAdmin):
    list_display = ['data', 'dia_semana', 'turno', 'colaborador', 'hora_inicio', 'hora_fim']
    list_filter = ['dia_semana', 'turno', 'data']
    search_fields = ['colaborador__nome_completo', 'observacoes']
    date_hierarchy = 'data'
    ordering = ['-data', 'hora_inicio']
    
    fieldsets = (
        ('Informações do Plantão', {
            'fields': ('colaborador', 'data', 'turno')
        }),
        ('Horários', {
            'fields': ('hora_inicio', 'hora_fim'),
            'description': 'Os horários são preenchidos automaticamente baseado no turno'
        }),
        ('Observações', {
            'fields': ('observacoes',),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['criado_em', 'atualizado_em']
    
    def get_readonly_fields(self, request, obj=None):
        """Tornar hora_inicio e hora_fim readonly pois são preenchidos automaticamente"""
        if obj:  # Editando
            return self.readonly_fields + ['hora_inicio', 'hora_fim']
        return self.readonly_fields


@admin.register(EscalaAutomatica)
class EscalaAutomaticaAdmin(admin.ModelAdmin):
    list_display = ['data_inicio', 'semanas_gerar', 'ativa', 'criada_em', 'criada_por']
    list_filter = ['ativa', 'data_inicio']
    date_hierarchy = 'criada_em'
    ordering = ['-criada_em']
    
    readonly_fields = ['criada_em', 'criada_por']
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.criada_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(TrocaPlantao)
class TrocaPlantaoAdmin(admin.ModelAdmin):
    list_display = ['solicitante', 'plantao_solicitante', 'destinatario', 'plantao_destinatario', 'status', 'criado_em']
    list_filter = ['status', 'criado_em']
    search_fields = ['solicitante__nome_completo', 'destinatario__nome_completo']

@admin.register(Notificacao)
class NotificacaoAdmin(admin.ModelAdmin):
    list_display = ['colaborador', 'tipo', 'titulo', 'lida', 'criado_em']
    list_filter = ['tipo', 'lida', 'criado_em']
    search_fields = ['colaborador__nome_completo', 'titulo']

@admin.register(TecnicoCampo)
class TecnicoCampoAdmin(admin.ModelAdmin):
    list_display = ['nome_completo', 'telefone', 'ordem_fila', 'ativo']
    list_filter = ['ativo']
    search_fields = ['nome_completo', 'telefone', 'email']

@admin.register(PlantaoTecnico)
class PlantaoTecnicoAdmin(admin.ModelAdmin):
    list_display = ['data', 'tipo', 'tecnico_principal', 'tecnico_dupla', 'hora_inicio', 'hora_fim']
    list_filter = ['tipo', 'data']
    search_fields = ['tecnico_principal__nome_completo', 'tecnico_dupla__nome_completo']

@admin.register(TrocaPlantaoTecnico)
class TrocaPlantaoTecnicoAdmin(admin.ModelAdmin):
    list_display = ['solicitante', 'destinatario', 'status', 'criado_em']
    list_filter = ['status', 'criado_em']

@admin.register(EscalaAutomaticaTecnico)
class EscalaAutomaticaTecnicoAdmin(admin.ModelAdmin):
    list_display = ['data_inicio', 'semanas_gerar', 'criada_por', 'criada_em']
    list_filter = ['criada_em']
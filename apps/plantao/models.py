from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, time
from django.utils import timezone

class Colaborador(models.Model):
    """Modelo para representar os colaboradores que fazem plantão"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='colaborador', null=True, blank=True)
    nome_completo = models.CharField(max_length=200)
    ativo = models.BooleanField(default=True)
    ordem_fila = models.IntegerField(default=0, help_text="Ordem na fila de plantões")
    
    class Meta:
        verbose_name = "Colaborador"
        verbose_name_plural = "Colaboradores"
        ordering = ['ordem_fila', 'nome_completo']
    
    def __str__(self):
        return self.nome_completo


class Plantao(models.Model):
    """Modelo principal para gerenciar plantões"""
    
    DIAS_SEMANA = [
        ('SAB', 'Sábado'),
        ('DOM', 'Domingo'),
    ]
    
    TURNOS = [
        ('SABADO_TARDE1', 'Sábado 13:00 - 17:00'),
        ('SABADO_TARDE2', 'Sábado 17:00 - 21:00'),
        ('DOMINGO_MANHA', 'Domingo 08:00 - 13:00'),
        ('DOMINGO_TARDE1', 'Domingo 13:00 - 17:00'),
        ('DOMINGO_TARDE2', 'Domingo 17:00 - 21:00'),
    ]
    
    colaborador = models.ForeignKey(
        Colaborador, 
        on_delete=models.CASCADE, 
        related_name='plantoes'
    )
    data = models.DateField(help_text="Data do plantão")
    dia_semana = models.CharField(max_length=3, choices=DIAS_SEMANA)
    turno = models.CharField(max_length=20, choices=TURNOS)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    observacoes = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Plantão"
        verbose_name_plural = "Plantões"
        ordering = ['data', 'hora_inicio']
        unique_together = ['data', 'turno']  # Não pode ter 2 pessoas no mesmo turno
    
    def __str__(self):
        return f"{self.colaborador.nome_completo} - {self.get_dia_semana_display()} {self.data} ({self.hora_inicio} - {self.hora_fim})"
    
    def clean(self):
        """Validações customizadas"""
        super().clean()
        
        # Validar que a hora de fim é maior que hora de início
        if self.hora_inicio and self.hora_fim:
            if self.hora_fim <= self.hora_inicio:
                raise ValidationError('Hora de fim deve ser maior que hora de início')
    
    @staticmethod
    def get_horarios_por_turno(turno):
        """Retorna os horários corretos baseado no turno"""
        horarios = {
            'SABADO_TARDE1': (time(13, 0), time(17, 0)),
            'SABADO_TARDE2': (time(17, 0), time(21, 0)),
            'DOMINGO_MANHA': (time(8, 0), time(13, 0)),
            'DOMINGO_TARDE1': (time(13, 0), time(17, 0)),
            'DOMINGO_TARDE2': (time(17, 0), time(21, 0)),
        }
        return horarios.get(turno, (None, None))
    
    def save(self, *args, **kwargs):
        # Definir automaticamente os horários baseado no turno
        if self.turno:
            inicio, fim = self.get_horarios_por_turno(self.turno)
            if inicio and fim:
                self.hora_inicio = inicio
                self.hora_fim = fim
        
        # Definir o dia da semana baseado na data
        if self.data:
            dia = self.data.weekday()
            if dia == 5:  # Sábado
                self.dia_semana = 'SAB'
            elif dia == 6:  # Domingo
                self.dia_semana = 'DOM'
        
        super().save(*args, **kwargs)


class EscalaAutomatica(models.Model):
    """Modelo para armazenar configurações de escala automática"""
    
    ativa = models.BooleanField(default=True)
    data_inicio = models.DateField()
    semanas_gerar = models.IntegerField(default=4, help_text="Quantas semanas gerar na escala")
    criada_em = models.DateTimeField(auto_now_add=True)
    criada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        verbose_name = "Escala Automática"
        verbose_name_plural = "Escalas Automáticas"
        ordering = ['-criada_em']
    
    def __str__(self):
        return f"Escala {self.data_inicio} - {self.semanas_gerar} semanas"

class TrocaPlantao(models.Model):
    """Modelo para gerenciar solicitações de troca de plantão"""
    
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ACEITA', 'Aceita'),
        ('RECUSADA', 'Recusada'),
        ('CANCELADA', 'Cancelada'),
    ]
    
    solicitante = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name='trocas_solicitadas'
    )
    plantao_solicitante = models.ForeignKey(
        Plantao,
        on_delete=models.CASCADE,
        related_name='troca_origem'
    )
    
    destinatario = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name='trocas_recebidas'
    )
    plantao_destinatario = models.ForeignKey(
        Plantao,
        on_delete=models.CASCADE,
        related_name='troca_destino'
    )
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDENTE')
    mensagem = models.TextField(blank=True, null=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        verbose_name = "Troca de Plantão"
        verbose_name_plural = "Trocas de Plantões"
        ordering = ['-criado_em']
    
    def __str__(self):
        return f"{self.solicitante.nome_completo} ↔ {self.destinatario.nome_completo} ({self.status})"
    
    def aceitar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser aceitas')
        
        temp_colab = self.plantao_solicitante.colaborador
        self.plantao_solicitante.colaborador = self.plantao_destinatario.colaborador
        self.plantao_destinatario.colaborador = temp_colab
        
        self.plantao_solicitante.save()
        self.plantao_destinatario.save()
        
        self.status = 'ACEITA'
        self.respondido_em = timezone.now()
        self.save()
    
    def recusar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser recusadas')
        
        self.status = 'RECUSADA'
        self.respondido_em = timezone.now()
        self.save()
    
    def cancelar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser canceladas')
        
        self.status = 'CANCELADA'
        self.respondido_em = timezone.now()
        self.save()


class Notificacao(models.Model):
    """Sistema de notificações"""
    
    TIPO_CHOICES = [
        ('TROCA_SOLICITADA', 'Solicitação de Troca'),
        ('TROCA_ACEITA', 'Troca Aceita'),
        ('TROCA_RECUSADA', 'Troca Recusada'),
        ('TROCA_CANCELADA', 'Troca Cancelada'),
    ]
    
    colaborador = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name='notificacoes'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=200)
    mensagem = models.TextField()
    
    troca = models.ForeignKey(
        TrocaPlantao,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='notificacoes'
    )
    
    lida = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ['-criado_em']
    
    def __str__(self):
        return f"{self.colaborador.nome_completo} - {self.titulo}"
    
    def marcar_como_lida(self):
        self.lida = True
        self.save()

# Adicione estes models ao apps/plantao/models.py

class TecnicoCampo(models.Model):
    """Modelo para Técnicos de Campo"""
    
    # Link com usuário (opcional)
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tecnico'
    )
    
    nome_completo = models.CharField(max_length=200)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    
    # Ordem na fila de plantões
    ordem_fila = models.IntegerField(default=0, help_text="Ordem na rotação de plantões")
    ativo = models.BooleanField(default=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Técnico de Campo"
        verbose_name_plural = "Técnicos de Campo"
        ordering = ['ordem_fila', 'nome_completo']
    
    def __str__(self):
        return self.nome_completo


class PlantaoTecnico(models.Model):
    """Modelo para Plantões de Técnicos de Campo"""
    
    TIPO_CHOICES = [
        ('SABADO_DUPLA', 'Sábado - Dupla (14:00-18:00)'),
        ('DOMINGO_SOLO', 'Domingo - Solo (Dia Todo)'),
        ('AVULSO_SOLO', 'Dia Avulso - Solo (Dia Todo)'),
    ]
    
    # Técnico principal
    tecnico_principal = models.ForeignKey(
        TecnicoCampo,
        on_delete=models.CASCADE,
        related_name='plantoes_principal'
    )
    
    # Técnico dupla (apenas para sábados)
    tecnico_dupla = models.ForeignKey(
        TecnicoCampo,
        on_delete=models.CASCADE,
        related_name='plantoes_dupla',
        null=True,
        blank=True,
        help_text="Apenas para plantões de sábado"
    )
    
    data = models.DateField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    
    # Horários fixos por tipo
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    
    observacoes = models.TextField(blank=True, null=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Plantão Técnico"
        verbose_name_plural = "Plantões Técnicos"
        ordering = ['data', 'hora_inicio']
        unique_together = ['data', 'tipo']  # Não pode ter 2 plantões do mesmo tipo no mesmo dia
    
    def __str__(self):
        if self.tipo == 'SABADO_DUPLA' and self.tecnico_dupla:
            return f"{self.tecnico_principal.nome_completo} + {self.tecnico_dupla.nome_completo} - {self.data}"
        return f"{self.tecnico_principal.nome_completo} - {self.data}"
    
    def save(self, *args, **kwargs):
        # Define horários automaticamente baseado no tipo
        if self.tipo == 'SABADO_DUPLA':
            self.hora_inicio = datetime.strptime('14:00', '%H:%M').time()
            self.hora_fim = datetime.strptime('18:00', '%H:%M').time()
        else:  # DOMINGO_SOLO ou AVULSO_SOLO
            self.hora_inicio = datetime.strptime('08:00', '%H:%M').time()
            self.hora_fim = datetime.strptime('18:00', '%H:%M').time()
        
        super().save(*args, **kwargs)
    
    @property
    def dia_semana(self):
        """Retorna dia da semana em português"""
        dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
        return dias[self.data.weekday()]


class TrocaPlantaoTecnico(models.Model):
    """Sistema de troca para técnicos"""
    
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ACEITA', 'Aceita'),
        ('RECUSADA', 'Recusada'),
        ('CANCELADA', 'Cancelada'),
    ]
    
    solicitante = models.ForeignKey(
        TecnicoCampo,
        on_delete=models.CASCADE,
        related_name='trocas_tecnico_solicitadas'
    )
    plantao_solicitante = models.ForeignKey(
        PlantaoTecnico,
        on_delete=models.CASCADE,
        related_name='troca_tecnico_origem'
    )
    
    destinatario = models.ForeignKey(
        TecnicoCampo,
        on_delete=models.CASCADE,
        related_name='trocas_tecnico_recebidas'
    )
    plantao_destinatario = models.ForeignKey(
        PlantaoTecnico,
        on_delete=models.CASCADE,
        related_name='troca_tecnico_destino'
    )
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDENTE')
    mensagem = models.TextField(blank=True, null=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        verbose_name = "Troca de Plantão - Técnico"
        verbose_name_plural = "Trocas de Plantões - Técnicos"
        ordering = ['-criado_em']
    
    def __str__(self):
        return f"{self.solicitante.nome_completo} ↔ {self.destinatario.nome_completo} ({self.status})"
    
    def aceitar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser aceitas')
        
        # Para sábados (dupla), troca apenas o técnico principal
        temp_principal = self.plantao_solicitante.tecnico_principal
        self.plantao_solicitante.tecnico_principal = self.plantao_destinatario.tecnico_principal
        self.plantao_destinatario.tecnico_principal = temp_principal
        
        self.plantao_solicitante.save()
        self.plantao_destinatario.save()
        
        self.status = 'ACEITA'
        self.respondido_em = timezone.now()
        self.save()
    
    def recusar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser recusadas')
        
        self.status = 'RECUSADA'
        self.respondido_em = timezone.now()
        self.save()
    
    def cancelar_troca(self):
        if self.status != 'PENDENTE':
            raise ValueError('Apenas trocas pendentes podem ser canceladas')
        
        self.status = 'CANCELADA'
        self.respondido_em = timezone.now()
        self.save()


class EscalaAutomaticaTecnico(models.Model):
    """Histórico de geração de escalas automáticas para técnicos"""
    
    criada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    data_inicio = models.DateField(help_text="Data do primeiro sábado")
    semanas_gerar = models.IntegerField(default=4)
    
    criada_em = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Escala Automática - Técnico"
        verbose_name_plural = "Escalas Automáticas - Técnicos"
        ordering = ['-criada_em']
    
    def __str__(self):
        return f"Escala Técnicos - {self.data_inicio} ({self.semanas_gerar} semanas)"


# Adicione este import no topo do arquivo se não tiver
from django.utils import timezone
from datetime import datetime
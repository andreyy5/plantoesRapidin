from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, time

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

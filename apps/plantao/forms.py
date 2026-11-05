from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS
from django.db.models import Q
from .models import Plantao, Colaborador, EscalaAutomatica
from datetime import datetime, timedelta

_INPUT = 'w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm text-[#50443C] focus:outline-none focus:border-[#E94920] focus:ring-2 focus:ring-[#E94920]/15 bg-white transition-colors'
_SELECT = _INPUT
_TEXTAREA = _INPUT + ' resize-none'
_CHECKBOX = 'w-4 h-4 accent-[#E94920] cursor-pointer'


class PlantaoForm(forms.ModelForm):
    class Meta:
        model = Plantao
        fields = ['colaborador', 'data', 'turno', 'observacoes']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date', 'class': _INPUT}),
            'colaborador': forms.Select(attrs={'class': _SELECT}),
            'turno': forms.Select(attrs={'class': _SELECT}),
            'observacoes': forms.Textarea(attrs={
                'class': _TEXTAREA,
                'rows': 3,
                'placeholder': 'Observações sobre o plantão (opcional)'
            }),
        }
        labels = {
            'colaborador': 'Colaborador',
            'data': 'Data do Plantão',
            'turno': 'Turno',
            'observacoes': 'Observações',
        }
        error_messages = {
            NON_FIELD_ERRORS: {
                'unique_together': 'Já existe um plantão neste turno nesta data. '
                                   'Edite o plantão existente em vez de cadastrar outro.',
            }
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ativos + o colaborador atual (ao editar plantão de alguém já inativo)
        filtro = Q(ativo=True)
        if self.instance.pk and self.instance.colaborador_id:
            filtro |= Q(pk=self.instance.colaborador_id)
        self.fields['colaborador'].queryset = Colaborador.objects.filter(filtro)

    def clean(self):
        cleaned = super().clean()
        data, turno = cleaned.get('data'), cleaned.get('turno')
        if data and turno:
            if turno.startswith('SABADO_') and data.weekday() != 5:
                self.add_error('data', 'Este turno é de sábado: escolha uma data que caia em um sábado.')
            elif turno.startswith('DOMINGO_') and data.weekday() != 6:
                self.add_error('data', 'Este turno é de domingo: escolha uma data que caia em um domingo.')
        return cleaned


class ColaboradorForm(forms.ModelForm):
    class Meta:
        model = Colaborador
        fields = ['nome_completo', 'ativo', 'ordem_fila', 'user']
        widgets = {
            'nome_completo': forms.TextInput(attrs={
                'class': _INPUT,
                'placeholder': 'Nome completo do colaborador'
            }),
            'ativo': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'ordem_fila': forms.NumberInput(attrs={'class': _INPUT, 'min': 0}),
            'user': forms.Select(attrs={'class': _SELECT}),
        }
        labels = {'user': 'Usuário de acesso'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apenas usuários ainda não vinculados (mais o usuário atual, ao editar)
        livres = Q(colaborador__isnull=True, tecnico__isnull=True)
        if self.instance.pk and self.instance.user_id:
            livres |= Q(pk=self.instance.user_id)
        campo = self.fields['user']
        campo.queryset = User.objects.filter(livres).order_by('username')
        campo.required = False
        campo.empty_label = 'Sem vínculo'
        campo.label_from_instance = lambda u: (
            f'{u.username} ({u.get_full_name()})' if u.get_full_name() else u.username
        )


class EscalaAutomaticaForm(forms.ModelForm):
    class Meta:
        model = EscalaAutomatica
        fields = ['data_inicio', 'semanas_gerar']
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date', 'class': _INPUT}),
            'semanas_gerar': forms.NumberInput(attrs={
                'class': _INPUT, 'min': 1, 'max': 12
            }),
        }
        labels = {
            'data_inicio': 'Data de Início (Sábado)',
            'semanas_gerar': 'Quantidade de Semanas',
        }

    def clean_data_inicio(self):
        data = self.cleaned_data.get('data_inicio')
        if data and data.weekday() != 5:
            raise forms.ValidationError('A data de início deve ser um sábado!')
        return data

    def clean_semanas_gerar(self):
        semanas = self.cleaned_data.get('semanas_gerar')
        if semanas is not None and not 1 <= semanas <= 12:
            raise forms.ValidationError('Informe de 1 a 12 semanas.')
        return semanas


class FiltroPlantaoForm(forms.Form):
    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': _INPUT}),
        label='Data Início'
    )
    data_fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': _INPUT}),
        label='Data Fim'
    )
    colaborador = forms.ModelChoiceField(
        queryset=Colaborador.objects.filter(ativo=True),
        required=False,
        widget=forms.Select(attrs={'class': _SELECT}),
        label='Colaborador',
        empty_label='Todos'
    )
    dia_semana = forms.ChoiceField(
        choices=[('', 'Todos')] + Plantao.DIAS_SEMANA,
        required=False,
        widget=forms.Select(attrs={'class': _SELECT}),
        label='Dia da Semana'
    )

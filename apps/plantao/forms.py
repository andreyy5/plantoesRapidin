from django import forms
from .models import Plantao, Colaborador, EscalaAutomatica
from datetime import datetime, timedelta

_INPUT = 'w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm text-[#50443C] focus:outline-none focus:border-[#E94920] bg-white transition-colors'
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['colaborador'].queryset = Colaborador.objects.filter(ativo=True)


class ColaboradorForm(forms.ModelForm):
    class Meta:
        model = Colaborador
        fields = ['nome_completo', 'ativo', 'ordem_fila']
        widgets = {
            'nome_completo': forms.TextInput(attrs={
                'class': _INPUT,
                'placeholder': 'Nome completo do colaborador'
            }),
            'ativo': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'ordem_fila': forms.NumberInput(attrs={'class': _INPUT, 'min': 0}),
        }


class EscalaAutomaticaForm(forms.ModelForm):
    class Meta:
        model = EscalaAutomatica
        fields = ['data_inicio', 'semanas_gerar']
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date', 'class': _INPUT}),
            'semanas_gerar': forms.NumberInput(attrs={
                'class': _INPUT, 'min': 1, 'max': 12, 'value': 4
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

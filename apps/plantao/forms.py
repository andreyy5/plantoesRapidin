from django import forms
from .models import Plantao, Colaborador, EscalaAutomatica
from datetime import datetime, timedelta

class PlantaoForm(forms.ModelForm):
    """Form para cadastro manual de plantão"""
    
    class Meta:
        model = Plantao
        fields = ['colaborador', 'data', 'turno', 'observacoes']
        widgets = {
            'data': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'colaborador': forms.Select(attrs={
                'class': 'form-control'
            }),
            'turno': forms.Select(attrs={
                'class': 'form-control'
            }),
            'observacoes': forms.Textarea(attrs={
                'class': 'form-control',
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
        # Filtrar apenas colaboradores ativos
        self.fields['colaborador'].queryset = Colaborador.objects.filter(ativo=True)


class ColaboradorForm(forms.ModelForm):
    """Form para cadastro de colaborador"""
    
    class Meta:
        model = Colaborador
        fields = ['nome_completo', 'ativo', 'ordem_fila']
        widgets = {
            'nome_completo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nome completo do colaborador'
            }),
            'ativo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'ordem_fila': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'help_text': 'Ordem na fila de plantões'
            }),
        }


class EscalaAutomaticaForm(forms.ModelForm):
    """Form para gerar escala automática"""
    
    class Meta:
        model = EscalaAutomatica
        fields = ['data_inicio', 'semanas_gerar']
        widgets = {
            'data_inicio': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'semanas_gerar': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 12,
                'value': 4
            }),
        }
        labels = {
            'data_inicio': 'Data de Início (Sábado)',
            'semanas_gerar': 'Quantidade de Semanas',
        }
    
    def clean_data_inicio(self):
        data = self.cleaned_data.get('data_inicio')
        if data and data.weekday() != 5:  # 5 = Sábado
            raise forms.ValidationError('A data de início deve ser um sábado!')
        return data


class FiltroPlantaoForm(forms.Form):
    """Form para filtrar plantões no dashboard"""
    
    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        label='Data Início'
    )
    
    data_fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        label='Data Fim'
    )
    
    colaborador = forms.ModelChoiceField(
        queryset=Colaborador.objects.filter(ativo=True),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label='Colaborador',
        empty_label='Todos'
    )
    
    dia_semana = forms.ChoiceField(
        choices=[('', 'Todos')] + Plantao.DIAS_SEMANA,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label='Dia da Semana'
    )

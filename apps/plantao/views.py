from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from datetime import datetime, timedelta
from .models import Plantao, Colaborador, EscalaAutomatica
from .forms import PlantaoForm, ColaboradorForm, EscalaAutomaticaForm, FiltroPlantaoForm


@login_required
def dashboard(request):
    """Dashboard principal mostrando plantões escalados"""
    
    # Filtros
    filtro_form = FiltroPlantaoForm(request.GET or None)
    
    # Query base
    plantoes = Plantao.objects.select_related('colaborador').all()
    
    # Aplicar filtros se o form for válido
    if filtro_form.is_valid():
        data_inicio = filtro_form.cleaned_data.get('data_inicio')
        data_fim = filtro_form.cleaned_data.get('data_fim')
        colaborador = filtro_form.cleaned_data.get('colaborador')
        dia_semana = filtro_form.cleaned_data.get('dia_semana')
        
        if data_inicio:
            plantoes = plantoes.filter(data__gte=data_inicio)
        if data_fim:
            plantoes = plantoes.filter(data__lte=data_fim)
        if colaborador:
            plantoes = plantoes.filter(colaborador=colaborador)
        if dia_semana:
            plantoes = plantoes.filter(dia_semana=dia_semana)
    else:
        # Por padrão, mostrar plantões das próximas 4 semanas
        hoje = datetime.now().date()
        data_fim = hoje + timedelta(weeks=4)
        plantoes = plantoes.filter(data__gte=hoje, data__lte=data_fim)
    
    # Agrupar plantões por semana
    plantoes_agrupados = {}
    for plantao in plantoes:
        # Calcular o início da semana (segunda-feira)
        inicio_semana = plantao.data - timedelta(days=plantao.data.weekday())
        semana_key = inicio_semana.strftime('%Y-%m-%d')
        
        if semana_key not in plantoes_agrupados:
            plantoes_agrupados[semana_key] = {
                'inicio': inicio_semana,
                'fim': inicio_semana + timedelta(days=6),
                'plantoes': []
            }
        plantoes_agrupados[semana_key]['plantoes'].append(plantao)
    
    # Ordenar por data
    plantoes_agrupados = dict(sorted(plantoes_agrupados.items()))
    
    context = {
        'plantoes_agrupados': plantoes_agrupados,
        'filtro_form': filtro_form,
        'total_plantoes': plantoes.count(),
    }
    
    return render(request, 'dashboard/home.html', context)


@login_required
def cadastrar_plantao(request):
    """Cadastro manual de plantão"""
    
    if request.method == 'POST':
        form = PlantaoForm(request.POST)
        if form.is_valid():
            try:
                plantao = form.save()
                messages.success(request, f'Plantão cadastrado com sucesso para {plantao.colaborador.nome_completo}!')
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'Erro ao cadastrar plantão: {str(e)}')
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
    else:
        form = PlantaoForm()
    
    context = {
        'form': form,
        'titulo': 'Cadastrar Plantão',
    }
    
    return render(request, 'dashboard/cadastrar_plantao.html', context)


@login_required
def editar_plantao(request, plantao_id):
    """Editar plantão existente"""
    
    plantao = get_object_or_404(Plantao, id=plantao_id)
    
    if request.method == 'POST':
        form = PlantaoForm(request.POST, instance=plantao)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Plantão atualizado com sucesso!')
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'Erro ao atualizar plantão: {str(e)}')
    else:
        form = PlantaoForm(instance=plantao)
    
    context = {
        'form': form,
        'titulo': 'Editar Plantão',
        'plantao': plantao,
    }
    
    return render(request, 'dashboard/cadastrar_plantao.html', context)


@login_required
def deletar_plantao(request, plantao_id):
    """Deletar plantão"""
    
    plantao = get_object_or_404(Plantao, id=plantao_id)
    
    if request.method == 'POST':
        colaborador_nome = plantao.colaborador.nome_completo
        plantao.delete()
        messages.success(request, f'Plantão de {colaborador_nome} removido com sucesso!')
        return redirect('dashboard')
    
    context = {
        'plantao': plantao,
    }
    
    return render(request, 'dashboard/confirmar_delete.html', context)


@login_required
def gerar_escala_automatica(request):
    """Gera escala automática seguindo a lógica da fila"""
    
    if request.method == 'POST':
        form = EscalaAutomaticaForm(request.POST)
        if form.is_valid():
            escala = form.save(commit=False)
            escala.criada_por = request.user
            escala.save()
            
            # Gerar os plantões
            try:
                plantoes_criados = _criar_plantoes_automaticos(
                    escala.data_inicio,
                    escala.semanas_gerar
                )
                messages.success(
                    request, 
                    f'Escala gerada com sucesso! {plantoes_criados} plantões criados.'
                )
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'Erro ao gerar escala: {str(e)}')
                escala.delete()
    else:
        # Sugerir próximo sábado como data inicial
        hoje = datetime.now().date()
        dias_ate_sabado = (5 - hoje.weekday()) % 7
        if dias_ate_sabado == 0:
            dias_ate_sabado = 7  # Se hoje é sábado, pegar o próximo
        proximo_sabado = hoje + timedelta(days=dias_ate_sabado)
        
        form = EscalaAutomaticaForm(initial={'data_inicio': proximo_sabado})
    
    context = {
        'form': form,
        'titulo': 'Gerar Escala Automática',
    }
    
    return render(request, 'dashboard/gerar_escala.html', context)


def _criar_plantoes_automaticos(data_inicio, semanas):
    """
    Lógica para criar plantões automaticamente seguindo a regra:
    - Sábado 13-17: Colaborador A
    - Sábado 17-21: Colaborador B
    - Domingo 08-13: Colaborador B (mesmo do sábado noite)
    - Domingo 13-17: Colaborador A (mesmo do sábado tarde)
    - Domingo 17-21: Próximo na fila (C)
    
    Na próxima semana, roda a fila
    """
    
    colaboradores = list(Colaborador.objects.filter(ativo=True).order_by('ordem_fila'))
    
    if len(colaboradores) < 2:
        raise ValueError('É necessário ter pelo menos 2 colaboradores ativos!')
    
    plantoes_criados = 0
    indice_fila = 0
    
    for semana in range(semanas):
        # Calcular data do sábado e domingo desta semana
        sabado = data_inicio + timedelta(weeks=semana)
        domingo = sabado + timedelta(days=1)
        
        # Pegar colaboradores desta semana usando a fila circular
        colab_sabado_tarde = colaboradores[indice_fila % len(colaboradores)]
        colab_sabado_noite = colaboradores[(indice_fila + 1) % len(colaboradores)]
        colab_domingo_noite = colaboradores[(indice_fila + 2) % len(colaboradores)]
        
        # Criar plantões do SÁBADO
        # Sábado 13:00 - 17:00
        Plantao.objects.create(
            colaborador=colab_sabado_tarde,
            data=sabado,
            turno='SABADO_TARDE1'
        )
        plantoes_criados += 1
        
        # Sábado 17:00 - 21:00
        Plantao.objects.create(
            colaborador=colab_sabado_noite,
            data=sabado,
            turno='SABADO_TARDE2'
        )
        plantoes_criados += 1
        
        # Criar plantões do DOMINGO
        # Domingo 08:00 - 13:00 (mesmo colaborador da noite de sábado)
        Plantao.objects.create(
            colaborador=colab_sabado_noite,
            data=domingo,
            turno='DOMINGO_MANHA'
        )
        plantoes_criados += 1
        
        # Domingo 13:00 - 17:00 (mesmo colaborador da tarde de sábado)
        Plantao.objects.create(
            colaborador=colab_sabado_tarde,
            data=domingo,
            turno='DOMINGO_TARDE1'
        )
        plantoes_criados += 1
        
        # Domingo 17:00 - 21:00 (próximo na fila)
        Plantao.objects.create(
            colaborador=colab_domingo_noite,
            data=domingo,
            turno='DOMINGO_TARDE2'
        )
        plantoes_criados += 1
        
        # Avançar na fila para próxima semana
        # Move 2 posições pois usamos 2 colaboradores principais
        indice_fila += 2
    
    return plantoes_criados


@login_required
def gerenciar_colaboradores(request):
    """Listar e gerenciar colaboradores"""
    
    colaboradores = Colaborador.objects.all().order_by('ordem_fila')
    
    context = {
        'colaboradores': colaboradores,
    }
    
    return render(request, 'dashboard/colaboradores.html', context)


@login_required
def cadastrar_colaborador(request):
    """Cadastrar novo colaborador"""
    
    if request.method == 'POST':
        form = ColaboradorForm(request.POST)
        if form.is_valid():
            colaborador = form.save()
            messages.success(request, f'Colaborador {colaborador.nome_completo} cadastrado com sucesso!')
            return redirect('gerenciar_colaboradores')
    else:
        # Sugerir próxima ordem na fila
        ultima_ordem = Colaborador.objects.count()
        form = ColaboradorForm(initial={'ordem_fila': ultima_ordem + 1, 'ativo': True})
    
    context = {
        'form': form,
        'titulo': 'Cadastrar Colaborador',
    }
    
    return render(request, 'dashboard/cadastrar_colaborador.html', context)


@login_required
def editar_colaborador(request, colaborador_id):
    """Editar colaborador existente"""
    
    colaborador = get_object_or_404(Colaborador, id=colaborador_id)
    
    if request.method == 'POST':
        form = ColaboradorForm(request.POST, instance=colaborador)
        if form.is_valid():
            form.save()
            messages.success(request, f'Colaborador {colaborador.nome_completo} atualizado com sucesso!')
            return redirect('gerenciar_colaboradores')
    else:
        form = ColaboradorForm(instance=colaborador)
    
    context = {
        'form': form,
        'titulo': 'Editar Colaborador',
        'colaborador': colaborador,
    }
    
    return render(request, 'dashboard/cadastrar_colaborador.html', context)

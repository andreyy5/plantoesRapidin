from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from datetime import datetime, timedelta
from .models import Plantao, Colaborador, EscalaAutomatica
from .forms import PlantaoForm, ColaboradorForm, EscalaAutomaticaForm, FiltroPlantaoForm


# ========== FUNÇÕES AUXILIARES DE PERMISSÃO ==========

def is_admin(user):
    """Verifica se o usuário é administrador"""
    return user.groups.filter(name='Administrador').exists() or user.is_superuser

def is_colaborador(user):
    """Verifica se o usuário é colaborador"""
    return user.groups.filter(name='Colaborador').exists()

def get_user_colaborador(user):
    """Retorna o objeto Colaborador vinculado ao usuário"""
    try:
        return Colaborador.objects.get(user=user)
    except Colaborador.DoesNotExist:
        return None


# ========== DECORATOR CUSTOMIZADO ==========

def admin_required(view_func):
    """Decorator que permite apenas administradores"""
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, '🔒 Você não tem permissão para acessar esta página.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# ========== VIEWS ==========

@login_required
def dashboard(request):
    """Dashboard principal - mostra plantões de acordo com permissão"""
    
    # Filtros
    filtro_form = FiltroPlantaoForm(request.GET or None)
    
    # Query base
    plantoes = Plantao.objects.select_related('colaborador').all()
    
    # Se for colaborador (e não admin), mostra APENAS seus plantões
    if is_colaborador(request.user) and not is_admin(request.user):
        colaborador = get_user_colaborador(request.user)
        if colaborador:
            plantoes = plantoes.filter(colaborador=colaborador)
        else:
            plantoes = Plantao.objects.none()
            messages.info(request, 'ℹ️ Você ainda não está vinculado a um colaborador.')
    
    # Aplicar filtros se o form for válido
    if filtro_form.is_valid():
        data_inicio = filtro_form.cleaned_data.get('data_inicio')
        data_fim = filtro_form.cleaned_data.get('data_fim')
        colaborador_filtro = filtro_form.cleaned_data.get('colaborador')
        dia_semana = filtro_form.cleaned_data.get('dia_semana')
        
        if data_inicio:
            plantoes = plantoes.filter(data__gte=data_inicio)
        if data_fim:
            plantoes = plantoes.filter(data__lte=data_fim)
        
        # Apenas administradores podem filtrar por colaborador
        if is_admin(request.user) and colaborador_filtro:
            plantoes = plantoes.filter(colaborador=colaborador_filtro)
            
        if dia_semana:
            plantoes = plantoes.filter(dia_semana=dia_semana)
    else:
        # Por padrão, mostrar plantões das próximas 4 semanas
        hoje = datetime.now().date()
        data_fim_padrao = hoje + timedelta(weeks=4)
        plantoes = plantoes.filter(data__gte=hoje, data__lte=data_fim_padrao)
    
    # Agrupar plantões por semana
    plantoes_agrupados = {}
    for plantao in plantoes:
        inicio_semana = plantao.data - timedelta(days=plantao.data.weekday())
        semana_key = inicio_semana.strftime('%Y-%m-%d')
        
        if semana_key not in plantoes_agrupados:
            plantoes_agrupados[semana_key] = {
                'inicio': inicio_semana,
                'fim': inicio_semana + timedelta(days=6),
                'plantoes': []
            }
        plantoes_agrupados[semana_key]['plantoes'].append(plantao)
    
    plantoes_agrupados = dict(sorted(plantoes_agrupados.items()))
    
    context = {
        'plantoes_agrupados': plantoes_agrupados,
        'filtro_form': filtro_form,
        'total_plantoes': plantoes.count(),
        'is_admin': is_admin(request.user),
        'is_colaborador': is_colaborador(request.user),
    }
    
    return render(request, 'dashboard/home.html', context)


@login_required
@admin_required
def cadastrar_plantao(request):
    """Cadastro manual de plantão - APENAS ADMIN"""
    
    if request.method == 'POST':
        form = PlantaoForm(request.POST)
        if form.is_valid():
            try:
                plantao = form.save()
                messages.success(request, f'✅ Plantão cadastrado com sucesso para {plantao.colaborador.nome_completo}!')
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'❌ Erro ao cadastrar plantão: {str(e)}')
        else:
            messages.error(request, '⚠️ Por favor, corrija os erros no formulário.')
    else:
        form = PlantaoForm()
    
    context = {
        'form': form,
        'titulo': 'Cadastrar Plantão',
    }
    
    return render(request, 'dashboard/cadastrar_plantao.html', context)


@login_required
@admin_required
def editar_plantao(request, plantao_id):
    """Editar plantão existente - APENAS ADMIN"""
    
    plantao = get_object_or_404(Plantao, id=plantao_id)
    
    if request.method == 'POST':
        form = PlantaoForm(request.POST, instance=plantao)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, '✅ Plantão atualizado com sucesso!')
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'❌ Erro ao atualizar plantão: {str(e)}')
    else:
        form = PlantaoForm(instance=plantao)
    
    context = {
        'form': form,
        'titulo': 'Editar Plantão',
        'plantao': plantao,
    }
    
    return render(request, 'dashboard/cadastrar_plantao.html', context)


@login_required
@admin_required
def deletar_plantao(request, plantao_id):
    """Deletar plantão - APENAS ADMIN"""
    
    plantao = get_object_or_404(Plantao, id=plantao_id)
    
    if request.method == 'POST':
        colaborador_nome = plantao.colaborador.nome_completo
        plantao.delete()
        messages.success(request, f'✅ Plantão de {colaborador_nome} removido com sucesso!')
        return redirect('dashboard')
    
    context = {
        'plantao': plantao,
    }
    
    return render(request, 'dashboard/confirmar_delete.html', context)


@login_required
@admin_required
def gerar_escala_automatica(request):
    """Gera escala automática - APENAS ADMIN"""
    
    if request.method == 'POST':
        form = EscalaAutomaticaForm(request.POST)
        if form.is_valid():
            escala = form.save(commit=False)
            escala.criada_por = request.user
            escala.save()
            
            try:
                plantoes_criados = _criar_plantoes_automaticos(
                    escala.data_inicio,
                    escala.semanas_gerar
                )
                messages.success(
                    request, 
                    f'✅ Escala gerada com sucesso! {plantoes_criados} plantões criados.'
                )
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f'❌ Erro ao gerar escala: {str(e)}')
                escala.delete()
    else:
        hoje = datetime.now().date()
        dias_ate_sabado = (5 - hoje.weekday()) % 7
        if dias_ate_sabado == 0:
            dias_ate_sabado = 7
        proximo_sabado = hoje + timedelta(days=dias_ate_sabado)
        
        form = EscalaAutomaticaForm(initial={'data_inicio': proximo_sabado})
    
    context = {
        'form': form,
        'titulo': 'Gerar Escala Automática',
    }
    
    return render(request, 'dashboard/gerar_escala.html', context)


def _criar_plantoes_automaticos(data_inicio, semanas):
    """Lógica para criar plantões automaticamente seguindo a regra da fila"""
    
    colaboradores = list(Colaborador.objects.filter(ativo=True).order_by('ordem_fila'))
    
    if len(colaboradores) < 2:
        raise ValueError('É necessário ter pelo menos 2 colaboradores ativos!')
    
    plantoes_criados = 0
    indice_fila = 0
    
    for semana in range(semanas):
        sabado = data_inicio + timedelta(weeks=semana)
        domingo = sabado + timedelta(days=1)
        
        colab_sabado_tarde = colaboradores[indice_fila % len(colaboradores)]
        colab_sabado_noite = colaboradores[(indice_fila + 1) % len(colaboradores)]
        colab_domingo_noite = colaboradores[(indice_fila + 2) % len(colaboradores)]
        
        Plantao.objects.create(colaborador=colab_sabado_tarde, data=sabado, turno='SABADO_TARDE1')
        Plantao.objects.create(colaborador=colab_sabado_noite, data=sabado, turno='SABADO_TARDE2')
        Plantao.objects.create(colaborador=colab_sabado_noite, data=domingo, turno='DOMINGO_MANHA')
        Plantao.objects.create(colaborador=colab_sabado_tarde, data=domingo, turno='DOMINGO_TARDE1')
        Plantao.objects.create(colaborador=colab_domingo_noite, data=domingo, turno='DOMINGO_TARDE2')
        
        plantoes_criados += 5
        indice_fila += 2
    
    return plantoes_criados


@login_required
@admin_required
def gerenciar_colaboradores(request):
    """Listar e gerenciar colaboradores - APENAS ADMIN"""
    
    colaboradores = Colaborador.objects.all().order_by('ordem_fila')
    
    context = {
        'colaboradores': colaboradores,
    }
    
    return render(request, 'dashboard/colaboradores.html', context)


@login_required
@admin_required
def cadastrar_colaborador(request):
    """Cadastrar novo colaborador - APENAS ADMIN"""
    
    if request.method == 'POST':
        form = ColaboradorForm(request.POST)
        if form.is_valid():
            colaborador = form.save()
            messages.success(request, f'✅ Colaborador {colaborador.nome_completo} cadastrado com sucesso!')
            return redirect('gerenciar_colaboradores')
    else:
        ultima_ordem = Colaborador.objects.count()
        form = ColaboradorForm(initial={'ordem_fila': ultima_ordem + 1, 'ativo': True})
    
    context = {
        'form': form,
        'titulo': 'Cadastrar Colaborador',
    }
    
    return render(request, 'dashboard/cadastrar_colaborador.html', context)


@login_required
@admin_required
def editar_colaborador(request, colaborador_id):
    """Editar colaborador existente - APENAS ADMIN"""
    
    colaborador = get_object_or_404(Colaborador, id=colaborador_id)
    
    if request.method == 'POST':
        form = ColaboradorForm(request.POST, instance=colaborador)
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ Colaborador {colaborador.nome_completo} atualizado com sucesso!')
            return redirect('gerenciar_colaboradores')
    else:
        form = ColaboradorForm(instance=colaborador)
    
    context = {
        'form': form,
        'titulo': 'Editar Colaborador',
        'colaborador': colaborador,
    }
    
    return render(request, 'dashboard/cadastrar_colaborador.html', context)
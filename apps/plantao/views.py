from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from datetime import datetime, timedelta
from .models import Plantao, Colaborador, EscalaAutomatica, TrocaPlantao, Notificacao
from .forms import PlantaoForm, ColaboradorForm, EscalaAutomaticaForm, FiltroPlantaoForm
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from io import BytesIO
from django.utils import timezone


# ========== FUNÇÕES AUXILIARES DE TIPO DE USUÁRIO ==========

def get_user_type(user):
    """
    Identifica o tipo de usuário baseado no model vinculado
    Retorna: 'admin', 'tecnico', 'colaborador' ou None
    """
    if not user.is_authenticated:
        return None
    
    # Admin sempre é admin
    if user.groups.filter(name='Administrador').exists() or user.is_superuser:
        return 'admin'
    
    # Verificar TecnicoCampo (DEVE VIR PRIMEIRO!)
    try:
        from .models import TecnicoCampo
        if hasattr(user, 'tecnico') and user.tecnico is not None:
            return 'tecnico'
    except:
        pass
    
    # Verificar Colaborador SAC
    try:
        if hasattr(user, 'colaborador') and user.colaborador is not None:
            return 'colaborador'
    except:
        pass
    
    return None


# ========== FUNÇÕES AUXILIARES DE PERMISSÃO (MANTIDAS PARA COMPATIBILIDADE) ==========

def is_admin(user):
    """Verifica se o usuário é administrador"""
    return user.groups.filter(name='Administrador').exists() or user.is_superuser


def is_colaborador(user):
    """Verifica se o usuário pertence ao grupo Colaborador"""
    return user.groups.filter(name='Colaborador').exists()


def get_user_colaborador(user):
    """Retorna o objeto Colaborador SAC vinculado ao usuário"""
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


# ========== VIEWS SAC ==========

@login_required
def dashboard(request):
    """Dashboard SAC - redireciona técnicos"""
    
    user_type = get_user_type(request.user)
    
    # 🔴 CRÍTICO: Se for técnico, redireciona para dashboard de técnicos
    if user_type == 'tecnico':
        messages.warning(request, '⚠️ Você é um técnico de campo.')
        return redirect('dashboard_tecnicos')
    
    # Filtros
    filtro_form = FiltroPlantaoForm(request.GET or None)
    
    # Query base
    plantoes = Plantao.objects.select_related('colaborador').all()
    
    # Buscar colaborador do usuário logado
    colaborador_user = get_user_colaborador(request.user)
    
    # Se for colaborador SAC (não admin), mostra APENAS seus plantões
    if user_type == 'colaborador':
        if colaborador_user:
            plantoes = plantoes.filter(colaborador=colaborador_user)
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
    
    # Contar colaboradores ativos
    colaboradores_count = Colaborador.objects.filter(ativo=True).count()
    
    context = {
        'plantoes_agrupados': plantoes_agrupados,
        'filtro_form': filtro_form,
        'total_plantoes': plantoes.count(),
        'colaboradores_count': colaboradores_count,
        'is_admin': is_admin(request.user),
        'is_colaborador': user_type == 'colaborador',
        'colaborador_logado': colaborador_user,
        'user_type': user_type,
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


# ========== EXPORTAR PDF SAC ==========

@login_required
def exportar_pdf(request):
    """Exporta plantões SAC em PDF"""
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#ff6600'),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    hoje = datetime.now().date()
    data_fim = hoje + timedelta(weeks=4)
    plantoes = Plantao.objects.select_related('colaborador').filter(
        data__gte=hoje,
        data__lte=data_fim
    ).order_by('data', 'hora_inicio')
    
    user_type = get_user_type(request.user)
    
    if user_type == 'colaborador':
        colaborador = get_user_colaborador(request.user)
        if colaborador:
            plantoes = plantoes.filter(colaborador=colaborador)
            titulo = f"Meus Plantões - {colaborador.nome_completo}"
        else:
            plantoes = Plantao.objects.none()
            titulo = "Meus Plantões"
    else:
        titulo = "Escala de Plantões - Todos os Colaboradores"
    
    elements.append(Paragraph(titulo, title_style))
    elements.append(Paragraph(
        f"Período: {hoje.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        subtitle_style
    ))
    
    if not plantoes.exists():
        elements.append(Paragraph(
            "Nenhum plantão encontrado para este período.",
            styles['Normal']
        ))
    else:
        plantoes_por_semana = {}
        for plantao in plantoes:
            inicio_semana = plantao.data - timedelta(days=plantao.data.weekday())
            semana_key = inicio_semana.strftime('%Y-%m-%d')
            
            if semana_key not in plantoes_por_semana:
                plantoes_por_semana[semana_key] = {
                    'inicio': inicio_semana,
                    'fim': inicio_semana + timedelta(days=6),
                    'plantoes': []
                }
            plantoes_por_semana[semana_key]['plantoes'].append(plantao)
        
        for semana_key, semana_data in sorted(plantoes_por_semana.items()):
            semana_style = ParagraphStyle(
                'SemanaHeader',
                parent=styles['Heading2'],
                fontSize=13,
                textColor=colors.HexColor('#ff6600'),
                spaceAfter=10,
                spaceBefore=15
            )
            
            elements.append(Paragraph(
                f"Semana de {semana_data['inicio'].strftime('%d/%m/%Y')} a {semana_data['fim'].strftime('%d/%m/%Y')}",
                semana_style
            ))
            
            data = [
                ['Data', 'Dia', 'Turno', 'Horário', 'Colaborador', 'Observações']
            ]
            
            for plantao in semana_data['plantoes']:
                data.append([
                    plantao.data.strftime('%d/%m/%Y'),
                    plantao.get_dia_semana_display(),
                    plantao.get_turno_display(),
                    f"{plantao.hora_inicio.strftime('%H:%M')} - {plantao.hora_fim.strftime('%H:%M')}",
                    plantao.colaborador.nome_completo,
                    plantao.observacoes[:30] + '...' if plantao.observacoes and len(plantao.observacoes) > 30 else plantao.observacoes or '--'
                ])
            
            table = Table(data, colWidths=[3*cm, 2.5*cm, 4*cm, 3.5*cm, 5*cm, 5*cm])
            
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ff6600')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#ff6600')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fff4e6')]),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]))
            
            elements.append(table)
            elements.append(Spacer(1, 0.5*cm))
    
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER
    )
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} - Sistema de Plantões Rapidin",
        footer_style
    ))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f"plantoes_sac_{hoje.strftime('%Y%m%d')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


# ========== TROCA DE PLANTÃO SAC ==========

@login_required
def solicitar_troca(request, plantao_id):
    """Permite colaborador solicitar troca de plantão"""
    
    meu_plantao = get_object_or_404(Plantao, id=plantao_id)
    colaborador_solicitante = get_user_colaborador(request.user)
    
    if not colaborador_solicitante or meu_plantao.colaborador != colaborador_solicitante:
        messages.error(request, '❌ Você só pode solicitar troca dos seus próprios plantões!')
        return redirect('dashboard')
    
    if meu_plantao.data < datetime.now().date():
        messages.error(request, '⏰ Não é possível trocar plantões que já passaram!')
        return redirect('dashboard')
    
    if request.method == 'POST':
        plantao_destino_id = request.POST.get('plantao_destino')
        mensagem = request.POST.get('mensagem', '')
        
        plantao_destino = get_object_or_404(Plantao, id=plantao_destino_id)
        
        if plantao_destino.colaborador == colaborador_solicitante:
            messages.error(request, '❌ Você não pode trocar com você mesmo!')
            return redirect('solicitar_troca', plantao_id=plantao_id)
        
        troca_existente = TrocaPlantao.objects.filter(
            solicitante=colaborador_solicitante,
            plantao_solicitante=meu_plantao,
            plantao_destinatario=plantao_destino,
            status='PENDENTE'
        ).exists()
        
        if troca_existente:
            messages.warning(request, '⚠️ Você já tem uma solicitação de troca pendente para este plantão!')
            return redirect('dashboard')
        
        troca = TrocaPlantao.objects.create(
            solicitante=colaborador_solicitante,
            plantao_solicitante=meu_plantao,
            destinatario=plantao_destino.colaborador,
            plantao_destinatario=plantao_destino,
            mensagem=mensagem,
            status='PENDENTE'
        )
        
        Notificacao.objects.create(
            colaborador=plantao_destino.colaborador,
            tipo='TROCA_SOLICITADA',
            titulo='Nova Solicitação de Troca de Plantão',
            mensagem=f"{colaborador_solicitante.nome_completo} quer trocar o plantão de {meu_plantao.data.strftime('%d/%m/%Y')} pelo seu plantão de {plantao_destino.data.strftime('%d/%m/%Y')}.",
            troca=troca
        )
        
        messages.success(request, f'✅ Solicitação de troca enviada para {plantao_destino.colaborador.nome_completo}!')
        return redirect('minhas_trocas')
    
    hoje = datetime.now().date()
    plantoes_disponiveis = Plantao.objects.select_related('colaborador').filter(
        data__gte=hoje
    ).exclude(
        colaborador=colaborador_solicitante
    ).order_by('data', 'hora_inicio')
    
    context = {
        'meu_plantao': meu_plantao,
        'plantoes_disponiveis': plantoes_disponiveis,
    }
    
    return render(request, 'dashboard/solicitar_troca.html', context)


@login_required
def minhas_trocas(request):
    """Lista todas as trocas (solicitadas e recebidas) do colaborador"""
    
    colaborador = get_user_colaborador(request.user)
    if not colaborador:
        messages.error(request, '❌ Você precisa estar vinculado a um colaborador!')
        return redirect('dashboard')
    
    trocas_solicitadas = TrocaPlantao.objects.filter(
        solicitante=colaborador
    ).select_related(
        'destinatario', 'plantao_solicitante', 'plantao_destinatario'
    ).order_by('-criado_em')
    
    trocas_recebidas = TrocaPlantao.objects.filter(
        destinatario=colaborador,
        status='PENDENTE'
    ).select_related(
        'solicitante', 'plantao_solicitante', 'plantao_destinatario'
    ).order_by('-criado_em')
    
    context = {
        'trocas_solicitadas': trocas_solicitadas,
        'trocas_recebidas': trocas_recebidas,
    }
    
    return render(request, 'dashboard/minhas_trocas.html', context)


@login_required
def responder_troca(request, troca_id, acao):
    """Aceitar ou recusar uma solicitação de troca"""
    
    troca = get_object_or_404(TrocaPlantao, id=troca_id)
    colaborador = get_user_colaborador(request.user)
    
    if troca.destinatario != colaborador:
        messages.error(request, '❌ Você não pode responder esta solicitação!')
        return redirect('minhas_trocas')
    
    if troca.status != 'PENDENTE':
        messages.warning(request, '⚠️ Esta solicitação já foi respondida!')
        return redirect('minhas_trocas')
    
    try:
        if acao == 'aceitar':
            troca.aceitar_troca()
            
            Notificacao.objects.create(
                colaborador=troca.solicitante,
                tipo='TROCA_ACEITA',
                titulo='Troca de Plantão Aceita! 🎉',
                mensagem=f"{troca.destinatario.nome_completo} aceitou trocar plantões com você!",
                troca=troca
            )
            
            messages.success(request, '✅ Troca aceita com sucesso! Os plantões foram trocados.')
            
        elif acao == 'recusar':
            troca.recusar_troca()
            
            Notificacao.objects.create(
                colaborador=troca.solicitante,
                tipo='TROCA_RECUSADA',
                titulo='Troca de Plantão Recusada',
                mensagem=f"{troca.destinatario.nome_completo} recusou sua solicitação de troca.",
                troca=troca
            )
            
            messages.info(request, '❌ Troca recusada.')
    
    except ValueError as e:
        messages.error(request, f'❌ Erro: {str(e)}')
    
    return redirect('minhas_trocas')


@login_required
def cancelar_troca(request, troca_id):
    """Cancela uma solicitação de troca (apenas o solicitante)"""
    
    troca = get_object_or_404(TrocaPlantao, id=troca_id)
    colaborador = get_user_colaborador(request.user)
    
    if troca.solicitante != colaborador:
        messages.error(request, '❌ Você não pode cancelar esta solicitação!')
        return redirect('minhas_trocas')
    
    if troca.status != 'PENDENTE':
        messages.warning(request, '⚠️ Não é possível cancelar esta solicitação!')
        return redirect('minhas_trocas')
    
    try:
        troca.cancelar_troca()
        
        Notificacao.objects.create(
            colaborador=troca.destinatario,
            tipo='TROCA_CANCELADA',
            titulo='Solicitação de Troca Cancelada',
            mensagem=f"{troca.solicitante.nome_completo} cancelou a solicitação de troca.",
            troca=troca
        )
        
        messages.success(request, '✅ Solicitação cancelada com sucesso!')
    
    except ValueError as e:
        messages.error(request, f'❌ Erro: {str(e)}')
    
    return redirect('minhas_trocas')


@login_required
def notificacoes(request):
    """Lista todas as notificações do colaborador"""
    
    colaborador = get_user_colaborador(request.user)
    if not colaborador:
        return redirect('dashboard')
    
    todas_notificacoes = Notificacao.objects.filter(
        colaborador=colaborador
    ).select_related('troca').order_by('-criado_em')
    
    if request.method == 'POST':
        notif_id = request.POST.get('notificacao_id')
        if notif_id:
            notif = Notificacao.objects.filter(id=notif_id, colaborador=colaborador).first()
            if notif:
                notif.marcar_como_lida()
    
    context = {
        'notificacoes': todas_notificacoes,
        'nao_lidas': todas_notificacoes.filter(lida=False).count(),
    }
    
    return render(request, 'dashboard/notificacoes.html', context)


@login_required
def marcar_notificacao_lida(request, notif_id):
    """Marca uma notificação como lida"""
    
    colaborador = get_user_colaborador(request.user)
    if not colaborador:
        return redirect('dashboard')
    
    notif = get_object_or_404(Notificacao, id=notif_id, colaborador=colaborador)
    notif.marcar_como_lida()
    
    return redirect('notificacoes')


def notificacoes_processor(request):
    """Context processor para adicionar notificações não lidas"""
    if request.user.is_authenticated:
        colaborador = get_user_colaborador(request.user)
        if colaborador:
            nao_lidas = Notificacao.objects.filter(
                colaborador=colaborador,
                lida=False
            ).count()
            return {'notificacoes_nao_lidas': nao_lidas}
    return {'notificacoes_nao_lidas': 0}


# ========== VIEWS TÉCNICOS DE CAMPO ==========

@login_required
def dashboard_tecnicos(request):
    """Dashboard de plantões de técnicos - redireciona colaboradores SAC"""
    
    from .models import PlantaoTecnico, TecnicoCampo
    
    user_type = get_user_type(request.user)
    
    # 🔴 CRÍTICO: Se for colaborador SAC, redireciona para dashboard SAC
    if user_type == 'colaborador':
        messages.warning(request, '⚠️ Você é um colaborador SAC.')
        return redirect('dashboard')
    
    plantoes = PlantaoTecnico.objects.select_related('tecnico_principal', 'tecnico_dupla').all()
    
    # Se for técnico (não admin), mostra apenas seus plantões
    if user_type == 'tecnico':
        try:
            tecnico = TecnicoCampo.objects.get(user=request.user)
            plantoes = plantoes.filter(
                Q(tecnico_principal=tecnico) | Q(tecnico_dupla=tecnico)
            )
        except TecnicoCampo.DoesNotExist:
            plantoes = PlantaoTecnico.objects.none()
            messages.info(request, 'ℹ️ Você ainda não está vinculado a um técnico.')
    
    hoje = datetime.now().date()
    data_fim = hoje + timedelta(weeks=4)
    plantoes = plantoes.filter(data__gte=hoje, data__lte=data_fim)
    
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
        'total_plantoes': plantoes.count(),
        'tecnicos_count': TecnicoCampo.objects.filter(ativo=True).count(),
        'is_admin': is_admin(request.user),
        'is_tecnico': user_type == 'tecnico',
        'user_type': user_type,
    }
    
    return render(request, 'dashboard/tecnicos/home.html', context)


@login_required
def exportar_pdf_tecnicos(request):
    """Exporta plantões técnicos em PDF"""
    
    from .models import PlantaoTecnico, TecnicoCampo
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="plantoes_tecnicos_{datetime.now().strftime("%Y%m%d")}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=landscape(A4),
                           topMargin=0.5*inch, bottomMargin=0.5*inch,
                           leftMargin=0.5*inch, rightMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#ff6600'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=20,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("ESCALA DE PLANTÕES - TÉCNICOS DE CAMPO", title_style))
    elements.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}", subtitle_style))
    
    # Buscar plantões
    plantoes = PlantaoTecnico.objects.select_related('tecnico_principal', 'tecnico_dupla').all()
    
    # Verificar tipo de usuário
    user_type = get_user_type(request.user)
    
    # 🔴 CORREÇÃO: Se for técnico (não admin), filtrar apenas seus plantões
    if user_type == 'tecnico':
        try:
            tecnico = TecnicoCampo.objects.get(user=request.user)
            plantoes = plantoes.filter(
                Q(tecnico_principal=tecnico) | Q(tecnico_dupla=tecnico)
            )
        except TecnicoCampo.DoesNotExist:
            plantoes = PlantaoTecnico.objects.none()
    
    # Filtrar próximas 4 semanas
    hoje = datetime.now().date()
    data_fim = hoje + timedelta(weeks=4)
    plantoes = plantoes.filter(data__gte=hoje, data__lte=data_fim).order_by('data', 'hora_inicio')
    
    # Agrupar por semana
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
    
    # Gerar tabelas por semana
    for semana_key in sorted(plantoes_agrupados.keys()):
        semana = plantoes_agrupados[semana_key]
        
        semana_style = ParagraphStyle(
            'SemanaStyle',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#ff6600'),
            spaceAfter=10,
            spaceBefore=15,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        )
        
        semana_text = f"Semana de {semana['inicio'].strftime('%d/%m/%Y')} a {semana['fim'].strftime('%d/%m/%Y')}"
        elements.append(Paragraph(semana_text, semana_style))
        
        # Cabeçalho da tabela
        data = [['Data', 'Dia', 'Tipo', 'Horário', 'Técnico(s)', 'Obs']]
        
        # Linhas da tabela
        for plantao in semana['plantoes']:
            # Mapear tipos
            tipo_map = {
                'SABADO_DUPLA': 'Dupla',
                'DOMINGO_SOLO': 'Solo',
                'AVULSO_SOLO': 'Avulso'
            }
            tipo = tipo_map.get(plantao.tipo, 'Desconhecido')
            
            # Técnicos (nome + dupla se houver)
            if plantao.tecnico_dupla:
                tecnicos = f"{plantao.tecnico_principal.nome_completo}\n+ {plantao.tecnico_dupla.nome_completo}"
            else:
                tecnicos = plantao.tecnico_principal.nome_completo
            
            # Dia da semana
            dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
            dia = dias[plantao.data.weekday()]
            
            # Observações truncadas
            obs = plantao.observacoes[:30] + '...' if plantao.observacoes and len(plantao.observacoes) > 30 else (plantao.observacoes or '--')
            
            data.append([
                plantao.data.strftime('%d/%m'),
                dia,
                tipo,
                f"{plantao.hora_inicio.strftime('%H:%M')}-{plantao.hora_fim.strftime('%H:%M')}",
                tecnicos,
                obs
            ])
        
        # Criar tabela
        table = Table(data, colWidths=[0.8*inch, 0.7*inch, 1*inch, 1.2*inch, 2.5*inch, 1.8*inch])
        
        # Estilizar tabela
        table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ff6600')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Corpo
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            
            # Grade e bordas
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Linhas alternadas
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 0.2*inch))
    
    # Se não houver plantões
    if not plantoes_agrupados:
        no_data_style = ParagraphStyle(
            'NoDataStyle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        elements.append(Spacer(1, 1*inch))
        elements.append(Paragraph("Nenhum plantão encontrado para o período selecionado.", no_data_style))
    
    # Rodapé
    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceBefore=30
    )
    elements.append(Spacer(1, 0.5*inch))
    elements.append(Paragraph("Sistema de Plantões Rapidin - Técnicos de Campo", footer_style))
    
    # Gerar PDF
    doc.build(elements)
    
    return response


@login_required
@admin_required
def cadastrar_plantao_tecnico(request):
    """Cadastrar plantão de técnico manualmente"""
    
    from .models import PlantaoTecnico, TecnicoCampo
    
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        data = request.POST.get('data')
        tecnico_principal_id = request.POST.get('tecnico_principal')
        tecnico_dupla_id = request.POST.get('tecnico_dupla')
        observacoes = request.POST.get('observacoes', '')
        
        try:
            tecnico_principal = TecnicoCampo.objects.get(id=tecnico_principal_id)
            
            plantao = PlantaoTecnico(
                tecnico_principal=tecnico_principal,
                data=data,
                tipo=tipo,
                observacoes=observacoes
            )
            
            if tipo == 'SABADO_DUPLA':
                if not tecnico_dupla_id:
                    messages.error(request, '⚠️ Plantão de sábado precisa de dupla!')
                    return redirect('cadastrar_plantao_tecnico')
                
                tecnico_dupla = TecnicoCampo.objects.get(id=tecnico_dupla_id)
                plantao.tecnico_dupla = tecnico_dupla
            
            plantao.save()
            messages.success(request, '✅ Plantão técnico cadastrado com sucesso!')
            return redirect('dashboard_tecnicos')
            
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)}')
    
    tecnicos = TecnicoCampo.objects.filter(ativo=True).order_by('nome_completo')
    
    context = {
        'tecnicos': tecnicos,
    }
    
    return render(request, 'dashboard/tecnicos/cadastrar_plantao.html', context)


@login_required
@admin_required
def gerar_escala_tecnicos(request):
    """Gera escala automática para técnicos"""
    
    from .models import PlantaoTecnico, TecnicoCampo, EscalaAutomaticaTecnico
    
    if request.method == 'POST':
        data_inicio = request.POST.get('data_inicio')
        semanas = int(request.POST.get('semanas', 4))
        
        try:
            data_inicio = datetime.strptime(data_inicio, '%Y-%m-%d').date()
            
            if data_inicio.weekday() != 5:
                dias_ate_sabado = (5 - data_inicio.weekday()) % 7
                if dias_ate_sabado == 0:
                    dias_ate_sabado = 7
                data_inicio = data_inicio + timedelta(days=dias_ate_sabado)
            
            plantoes_criados = _criar_plantoes_tecnicos(data_inicio, semanas)
            
            EscalaAutomaticaTecnico.objects.create(
                criada_por=request.user,
                data_inicio=data_inicio,
                semanas_gerar=semanas
            )
            
            messages.success(request, f'✅ Escala gerada! {plantoes_criados} plantões criados.')
            return redirect('dashboard_tecnicos')
            
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)}')
    
    hoje = datetime.now().date()
    dias_ate_sabado = (5 - hoje.weekday()) % 7
    if dias_ate_sabado == 0:
        dias_ate_sabado = 7
    proximo_sabado = hoje + timedelta(days=dias_ate_sabado)
    
    context = {
        'data_sugerida': proximo_sabado,
    }
    
    return render(request, 'dashboard/tecnicos/gerar_escala.html', context)


def _criar_plantoes_tecnicos(data_inicio, semanas):
    """Lógica para criar plantões de técnicos automaticamente"""
    
    from .models import PlantaoTecnico, TecnicoCampo
    
    tecnicos = list(TecnicoCampo.objects.filter(ativo=True).order_by('ordem_fila'))
    
    if len(tecnicos) < 2:
        raise ValueError('É necessário ter pelo menos 2 técnicos ativos!')
    
    plantoes_criados = 0
    indice = 0
    
    for semana in range(semanas):
        sabado = data_inicio + timedelta(weeks=semana)
        domingo = sabado + timedelta(days=1)
        
        tec1 = tecnicos[indice % len(tecnicos)]
        tec2 = tecnicos[(indice + 1) % len(tecnicos)]
        
        PlantaoTecnico.objects.create(
            tecnico_principal=tec1,
            tecnico_dupla=tec2,
            data=sabado,
            tipo='SABADO_DUPLA'
        )
        plantoes_criados += 1
        
        tec_domingo = tecnicos[(indice + 2) % len(tecnicos)]
        
        PlantaoTecnico.objects.create(
            tecnico_principal=tec_domingo,
            data=domingo,
            tipo='DOMINGO_SOLO'
        )
        plantoes_criados += 1
        
        indice += 3
    
    return plantoes_criados


@login_required
@admin_required
def gerenciar_tecnicos(request):
    """Lista todos os técnicos"""
    
    from .models import TecnicoCampo
    
    tecnicos = TecnicoCampo.objects.all().order_by('ordem_fila')
    
    context = {
        'tecnicos': tecnicos,
    }
    
    return render(request, 'dashboard/tecnicos/gerenciar_tecnicos.html', context)


@login_required
@admin_required
def cadastrar_tecnico(request):
    """Cadastrar novo técnico"""
    
    from .models import TecnicoCampo
    
    if request.method == 'POST':
        nome = request.POST.get('nome_completo')
        telefone = request.POST.get('telefone', '')
        email = request.POST.get('email', '')
        ordem = request.POST.get('ordem_fila', 0)
        ativo = request.POST.get('ativo') == 'on'
        
        TecnicoCampo.objects.create(
            nome_completo=nome,
            telefone=telefone,
            email=email,
            ordem_fila=ordem,
            ativo=ativo
        )
        
        messages.success(request, f'✅ Técnico {nome} cadastrado!')
        return redirect('gerenciar_tecnicos')
    
    ultima_ordem = TecnicoCampo.objects.count()
    
    context = {
        'ordem_sugerida': ultima_ordem + 1,
    }
    
    return render(request, 'dashboard/tecnicos/cadastrar_tecnico.html', context)


@login_required
@admin_required
def editar_plantao_tecnico(request, plantao_id):
    """Editar plantão de técnico"""
    
    from .models import PlantaoTecnico, TecnicoCampo
    
    plantao = get_object_or_404(PlantaoTecnico, id=plantao_id)
    
    if request.method == 'POST':
        plantao.tecnico_principal_id = request.POST.get('tecnico_principal')
        
        if plantao.tipo == 'SABADO_DUPLA':
            plantao.tecnico_dupla_id = request.POST.get('tecnico_dupla')
        
        plantao.observacoes = request.POST.get('observacoes', '')
        plantao.save()
        
        messages.success(request, '✅ Plantão atualizado!')
        return redirect('dashboard_tecnicos')
    
    tecnicos = TecnicoCampo.objects.filter(ativo=True)
    
    context = {
        'plantao': plantao,
        'tecnicos': tecnicos,
    }
    
    return render(request, 'dashboard/tecnicos/editar_plantao.html', context)


@login_required
@admin_required
def deletar_plantao_tecnico(request, plantao_id):
    """Deletar plantão de técnico"""
    
    from .models import PlantaoTecnico
    
    plantao = get_object_or_404(PlantaoTecnico, id=plantao_id)
    
    if request.method == 'POST':
        plantao.delete()
        messages.success(request, '✅ Plantão removido!')
        return redirect('dashboard_tecnicos')
    
    context = {
        'plantao': plantao,
    }
    
    return render(request, 'dashboard/tecnicos/confirmar_delete.html', context)


@login_required
@admin_required
def editar_tecnico(request, tecnico_id):
    """Editar técnico existente"""
    
    from .models import TecnicoCampo
    
    tecnico = get_object_or_404(TecnicoCampo, id=tecnico_id)
    
    if request.method == 'POST':
        tecnico.nome_completo = request.POST.get('nome_completo')
        tecnico.telefone = request.POST.get('telefone', '')
        tecnico.email = request.POST.get('email', '')
        tecnico.ordem_fila = request.POST.get('ordem_fila', 0)
        tecnico.ativo = request.POST.get('ativo') == 'on'
        
        tecnico.save()
        
        messages.success(request, f'✅ Técnico {tecnico.nome_completo} atualizado!')
        return redirect('gerenciar_tecnicos')
    
    context = {
        'tecnico': tecnico,
    }
    
    return render(request, 'dashboard/tecnicos/editar_tecnico.html', context)
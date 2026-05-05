from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from datetime import datetime, timedelta
from .models import Plantao, Colaborador, EscalaAutomatica, TrocaPlantao, Notificacao
from .forms import PlantaoForm, ColaboradorForm, EscalaAutomaticaForm, FiltroPlantaoForm
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
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
        hoje = datetime.now().date()
        inicio_semana_atual = hoje - timedelta(days=hoje.weekday())  # ← Calcula segunda-feira
        data_fim = inicio_semana_atual + timedelta(weeks=8) - timedelta(days=1)  # ← 8 semanas completas
        plantoes = plantoes.filter(data__gte=inicio_semana_atual, data__lte=data_fim)
    
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

def _pdf_rodape(canvas, doc):
    """Rodapé com número de página em todos os documentos PDF."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#e5e7eb'))
    canvas.setLineWidth(0.4)
    y = doc.bottomMargin - 0.5 * cm
    canvas.line(doc.leftMargin, y, doc.leftMargin + doc.width, y)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(colors.HexColor('#9ca3af'))
    canvas.drawString(
        doc.leftMargin, y - 0.35 * cm,
        f"Rapidin Plantões — gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
    )
    canvas.drawRightString(
        doc.leftMargin + doc.width, y - 0.35 * cm,
        f"Página {canvas.getPageNumber()}"
    )
    canvas.restoreState()


@login_required
def exportar_pdf(request):
    """Exporta plantões SAC em PDF — portrait A4."""

    COR          = colors.HexColor('#E94920')
    COR_TEXTO    = colors.HexColor('#50443C')
    COR_ZEBRA    = colors.HexColor('#fdf5f3')
    COR_BORDA    = colors.HexColor('#e5e7eb')
    COR_SEM_BG   = colors.HexColor('#fff8f6')

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2.2 * cm,
    )

    # Largura útil da página
    W = doc.width

    # ── Dados ──────────────────────────────────────────────────────────────
    hoje     = datetime.now().date()
    data_fim = hoje + timedelta(weeks=4)

    plantoes = (
        Plantao.objects
        .select_related('colaborador')
        .filter(data__gte=hoje, data__lte=data_fim)
        .order_by('data', 'hora_inicio')
    )

    user_type = get_user_type(request.user)
    if user_type == 'colaborador':
        colaborador = get_user_colaborador(request.user)
        if colaborador:
            plantoes = plantoes.filter(colaborador=colaborador)
            titulo = f"Meus Plantões — {colaborador.nome_completo}"
        else:
            plantoes = Plantao.objects.none()
            titulo   = "Meus Plantões"
    else:
        titulo = "Escala de Plantões — SAC"

    # ── Estilos ─────────────────────────────────────────────────────────────
    def st(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=9, textColor=COR_TEXTO, leading=12)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    st_th  = st('th', fontName='Helvetica-Bold', fontSize=8,
                textColor=colors.white, alignment=TA_CENTER, leading=11)
    st_td  = st('td', fontSize=8, leading=11)
    st_tdc = st('tdc', fontSize=8, leading=11, alignment=TA_CENTER)

    elements = []

    # ── Cabeçalho do documento ──────────────────────────────────────────────
    hdr = Table(
        [[Paragraph(f'<b>{titulo}</b>',
                    ParagraphStyle('ht', fontName='Helvetica-Bold', fontSize=13,
                                   textColor=colors.white, alignment=TA_CENTER, leading=16))]],
        colWidths=[W],
    )
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), COR),
        ('TOPPADDING',    (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    elements.append(hdr)
    elements.append(Spacer(1, 0.25 * cm))
    elements.append(Paragraph(
        f"Período: {hoje.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        ParagraphStyle('sub', fontName='Helvetica', fontSize=8,
                       textColor=colors.HexColor('#9ca3af'),
                       alignment=TA_CENTER, spaceAfter=14),
    ))

    # ── Sem dados ───────────────────────────────────────────────────────────
    if not plantoes.exists():
        elements.append(Spacer(1, 1.5 * cm))
        elements.append(Paragraph(
            "Nenhum plantão encontrado para este período.",
            ParagraphStyle('vz', fontName='Helvetica', fontSize=10,
                           textColor=colors.grey, alignment=TA_CENTER),
        ))
    else:
        # Agrupar por semana
        semanas = {}
        for p in plantoes:
            ini = p.data - timedelta(days=p.data.weekday())
            k   = ini.strftime('%Y-%m-%d')
            if k not in semanas:
                semanas[k] = {'inicio': ini, 'fim': ini + timedelta(days=6), 'plantoes': []}
            semanas[k]['plantoes'].append(p)

        # Colunas — portrait A4 (~18 cm útil)
        COL = [2.3*cm, 1.8*cm, 3.4*cm, 2.8*cm, 4.4*cm, 3.3*cm]

        for k in sorted(semanas):
            sd = semanas[k]
            label = f"Semana de {sd['inicio'].strftime('%d/%m/%Y')} a {sd['fim'].strftime('%d/%m/%Y')}"

            # Faixa de semana
            sem_t = Table(
                [[Paragraph(f'<b>{label}</b>',
                            ParagraphStyle('sl', fontName='Helvetica-Bold', fontSize=9,
                                           textColor=COR, leading=12))]],
                colWidths=[W],
            )
            sem_t.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, -1), COR_SEM_BG),
                ('TOPPADDING',    (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('LEFTPADDING',   (0, 0), (-1, -1), 10),
                ('LINEBELOW',     (0, 0), (-1, -1), 1.2, COR),
            ]))
            elements.append(sem_t)

            # Tabela de plantões
            rows = [[
                Paragraph('Data',        st_th),
                Paragraph('Dia',         st_th),
                Paragraph('Turno',       st_th),
                Paragraph('Horário',     st_th),
                Paragraph('Colaborador', st_th),
                Paragraph('Observações', st_th),
            ]]
            for p in sd['plantoes']:
                obs = (p.observacoes[:38] + '…') if p.observacoes and len(p.observacoes) > 38 else (p.observacoes or '—')
                rows.append([
                    Paragraph(p.data.strftime('%d/%m/%Y'),                              st_tdc),
                    Paragraph(p.get_dia_semana_display(),                               st_tdc),
                    Paragraph(p.get_turno_display(),                                    st_td),
                    Paragraph(f"{p.hora_inicio.strftime('%H:%M')} – {p.hora_fim.strftime('%H:%M')}", st_tdc),
                    Paragraph(p.colaborador.nome_completo,                              st_td),
                    Paragraph(obs,                                                      st_td),
                ])

            row_bgs = [('BACKGROUND', (0, i), (-1, i),
                        colors.white if i % 2 == 1 else COR_ZEBRA)
                       for i in range(1, len(rows))]

            t = Table(rows, colWidths=COL, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, 0), COR),
                ('TOPPADDING',    (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEBELOW',     (0, 0), (-1, -1), 0.3, COR_BORDA),
                ('LINEAFTER',     (0, 0), (-1, -1), 0.3, COR_BORDA),
                *row_bgs,
            ]))
            elements.append(t)
            elements.append(Spacer(1, 0.7 * cm))

    doc.build(elements, onFirstPage=_pdf_rodape, onLaterPages=_pdf_rodape)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="plantoes_sac_{hoje.strftime("%Y%m%d")}.pdf"'
    )
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
    
    # ===== APLICAR FILTROS (Admin apenas) =====
    filtros_aplicados = False
    
    if is_admin(request.user):
        data_inicio_filtro = request.GET.get('data_inicio')
        data_fim_filtro = request.GET.get('data_fim')
        tipo_filtro = request.GET.get('tipo')
        
        if data_inicio_filtro:
            try:
                data_inicio_filtro = datetime.strptime(data_inicio_filtro, '%Y-%m-%d').date()
                plantoes = plantoes.filter(data__gte=data_inicio_filtro)
                filtros_aplicados = True
            except:
                pass
        
        if data_fim_filtro:
            try:
                data_fim_filtro = datetime.strptime(data_fim_filtro, '%Y-%m-%d').date()
                plantoes = plantoes.filter(data__lte=data_fim_filtro)
                filtros_aplicados = True
            except:
                pass
        
        if tipo_filtro:
            plantoes = plantoes.filter(tipo=tipo_filtro)
            filtros_aplicados = True
    
    # ===== FILTRO PADRÃO (apenas se NÃO houver filtros manuais) =====
    # 🔧 CORREÇÃO DO BUG: Começar do início da SEMANA ATUAL, não de hoje!
    if not filtros_aplicados:
        hoje = datetime.now().date()
        
        # Calcular início da semana atual (segunda-feira = dia 0)
        inicio_semana_atual = hoje - timedelta(days=hoje.weekday())
        
        # Mostrar desde o início da semana atual até 8 semanas completas
        data_fim = inicio_semana_atual + timedelta(weeks=8) - timedelta(days=1)
        
        plantoes = plantoes.filter(data__gte=inicio_semana_atual, data__lte=data_fim)
    
    # Ordenar por data
    plantoes = plantoes.order_by('data', 'hora_inicio')
    
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
    """Exporta plantões técnicos em PDF — portrait A4."""

    from .models import PlantaoTecnico, TecnicoCampo

    COR        = colors.HexColor('#E94920')
    COR_TEXTO  = colors.HexColor('#50443C')
    COR_ZEBRA  = colors.HexColor('#fdf5f3')
    COR_BORDA  = colors.HexColor('#e5e7eb')
    COR_SEM_BG = colors.HexColor('#fff8f6')

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2.2 * cm,
    )
    W = doc.width

    # ── Dados ──────────────────────────────────────────────────────────────
    hoje     = datetime.now().date()
    data_fim = hoje + timedelta(weeks=4)

    plantoes = (
        PlantaoTecnico.objects
        .select_related('tecnico_principal', 'tecnico_dupla')
        .all()
    )

    user_type = get_user_type(request.user)
    if user_type == 'tecnico':
        try:
            tecnico  = TecnicoCampo.objects.get(user=request.user)
            plantoes = plantoes.filter(
                Q(tecnico_principal=tecnico) | Q(tecnico_dupla=tecnico)
            )
            titulo = f"Meus Plantões — {tecnico.nome_completo}"
        except TecnicoCampo.DoesNotExist:
            plantoes = PlantaoTecnico.objects.none()
            titulo   = "Meus Plantões"
    else:
        titulo = "Escala de Plantões — Técnicos de Campo"

    plantoes = plantoes.filter(
        data__gte=hoje, data__lte=data_fim
    ).order_by('data', 'hora_inicio')

    # ── Estilos ─────────────────────────────────────────────────────────────
    def st(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=9, textColor=COR_TEXTO, leading=12)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    st_th  = st('th', fontName='Helvetica-Bold', fontSize=8,
                textColor=colors.white, alignment=TA_CENTER, leading=11)
    st_td  = st('td', fontSize=8, leading=11)
    st_tdc = st('tdc', fontSize=8, leading=11, alignment=TA_CENTER)

    elements = []

    # ── Cabeçalho do documento ──────────────────────────────────────────────
    hdr = Table(
        [[Paragraph(f'<b>{titulo}</b>',
                    ParagraphStyle('ht', fontName='Helvetica-Bold', fontSize=13,
                                   textColor=colors.white, alignment=TA_CENTER, leading=16))]],
        colWidths=[W],
    )
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), COR),
        ('TOPPADDING',    (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    elements.append(hdr)
    elements.append(Spacer(1, 0.25 * cm))
    elements.append(Paragraph(
        f"Período: {hoje.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        ParagraphStyle('sub', fontName='Helvetica', fontSize=8,
                       textColor=colors.HexColor('#9ca3af'),
                       alignment=TA_CENTER, spaceAfter=14),
    ))

    # ── Agrupar por semana ──────────────────────────────────────────────────
    semanas = {}
    for p in plantoes:
        ini = p.data - timedelta(days=p.data.weekday())
        k   = ini.strftime('%Y-%m-%d')
        if k not in semanas:
            semanas[k] = {'inicio': ini, 'fim': ini + timedelta(days=6), 'plantoes': []}
        semanas[k]['plantoes'].append(p)

    if not semanas:
        elements.append(Spacer(1, 1.5 * cm))
        elements.append(Paragraph(
            "Nenhum plantão encontrado para este período.",
            ParagraphStyle('vz', fontName='Helvetica', fontSize=10,
                           textColor=colors.grey, alignment=TA_CENTER),
        ))
    else:
        TIPO_MAP = {'SABADO_DUPLA': 'Dupla', 'DOMINGO_SOLO': 'Solo', 'AVULSO_SOLO': 'Avulso'}
        DIAS     = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

        # Colunas — portrait A4 (~18 cm útil)
        COL = [2.1*cm, 1.6*cm, 2.5*cm, 2.8*cm, 5.3*cm, 3.7*cm]

        for k in sorted(semanas):
            sd    = semanas[k]
            label = f"Semana de {sd['inicio'].strftime('%d/%m/%Y')} a {sd['fim'].strftime('%d/%m/%Y')}"

            # Faixa de semana
            sem_t = Table(
                [[Paragraph(f'<b>{label}</b>',
                            ParagraphStyle('sl', fontName='Helvetica-Bold', fontSize=9,
                                           textColor=COR, leading=12))]],
                colWidths=[W],
            )
            sem_t.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, -1), COR_SEM_BG),
                ('TOPPADDING',    (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('LEFTPADDING',   (0, 0), (-1, -1), 10),
                ('LINEBELOW',     (0, 0), (-1, -1), 1.2, COR),
            ]))
            elements.append(sem_t)

            # Tabela de plantões
            rows = [[
                Paragraph('Data',       st_th),
                Paragraph('Dia',        st_th),
                Paragraph('Tipo',       st_th),
                Paragraph('Horário',    st_th),
                Paragraph('Técnico(s)', st_th),
                Paragraph('Obs.',       st_th),
            ]]

            for p in sd['plantoes']:
                tipo = TIPO_MAP.get(p.tipo, p.tipo)
                dia  = DIAS[p.data.weekday()]
                obs  = (p.observacoes[:38] + '…') if p.observacoes and len(p.observacoes) > 38 else (p.observacoes or '—')

                if p.tecnico_dupla:
                    tecs = Paragraph(
                        f"{p.tecnico_principal.nome_completo}<br/>"
                        f"<font size='7' color='#9ca3af'>+ {p.tecnico_dupla.nome_completo}</font>",
                        st_td,
                    )
                else:
                    tecs = Paragraph(p.tecnico_principal.nome_completo, st_td)

                rows.append([
                    Paragraph(p.data.strftime('%d/%m/%Y'),                              st_tdc),
                    Paragraph(dia,                                                       st_tdc),
                    Paragraph(tipo,                                                      st_tdc),
                    Paragraph(f"{p.hora_inicio.strftime('%H:%M')} – {p.hora_fim.strftime('%H:%M')}", st_tdc),
                    tecs,
                    Paragraph(obs, st_td),
                ])

            row_bgs = [('BACKGROUND', (0, i), (-1, i),
                        colors.white if i % 2 == 1 else COR_ZEBRA)
                       for i in range(1, len(rows))]

            t = Table(rows, colWidths=COL, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, 0), COR),
                ('TOPPADDING',    (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEBELOW',     (0, 0), (-1, -1), 0.3, COR_BORDA),
                ('LINEAFTER',     (0, 0), (-1, -1), 0.3, COR_BORDA),
                *row_bgs,
            ]))
            elements.append(t)
            elements.append(Spacer(1, 0.7 * cm))

    doc.build(elements, onFirstPage=_pdf_rodape, onLaterPages=_pdf_rodape)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="plantoes_tecnicos_{hoje.strftime("%Y%m%d")}.pdf"'
    )
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
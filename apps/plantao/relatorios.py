"""
Relatórios de plantões (SAC e técnicos de campo): dados consolidados e PDF.
"""

from collections import OrderedDict
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from django.db.models import Q
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import escala
from .models import Colaborador, Plantao, PlantaoTecnico, TecnicoCampo

AREAS = (('sac', 'SAC'), ('tecnicos', 'Técnicos de campo'))
DIAS = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')


def _horas(inicio, fim):
    if not inicio or not fim:
        return 0.0
    return (datetime.combine(datetime.min, fim) - datetime.combine(datetime.min, inicio)).seconds / 3600


def _fmt_horas(h):
    return f'{h:.0f}h' if float(h).is_integer() else f'{h:.1f}h'.replace('.', ',')


class _Linha:
    """Acumulador do resumo por pessoa."""

    def __init__(self, nome):
        self.nome = nome
        self.plantoes = 0
        self.sabados = 0
        self.domingos = 0
        self.avulsos = 0
        self.horas = 0.0
        self._fds = set()

    def somar(self, data, horas):
        self.plantoes += 1
        self.horas += horas
        dia = data.weekday()
        if dia == 5:
            self.sabados += 1
        elif dia == 6:
            self.domingos += 1
        else:
            self.avulsos += 1
        sabado = escala.sabado_do_fim_de_semana(data)
        if sabado:
            self._fds.add(sabado)

    @property
    def fins_de_semana(self):
        return len(self._fds)

    @property
    def horas_fmt(self):
        return _fmt_horas(self.horas)


def _totais(linhas):
    total = _Linha('Total')
    for l in linhas:
        total.plantoes += l.plantoes
        total.sabados += l.sabados
        total.domingos += l.domingos
        total.avulsos += l.avulsos
        total.horas += l.horas
        total._fds |= l._fds
    return total


def _agrupar_por_semana(itens):
    semanas = OrderedDict()
    for item in itens:
        inicio = item['data'] - timedelta(days=item['data'].weekday())
        semanas.setdefault(inicio, []).append(item)
    return [{'inicio': i, 'fim': i + timedelta(days=6), 'itens': v} for i, v in semanas.items()]


def dados_sac(inicio, fim, colaborador=None):
    qs = (Plantao.objects.select_related('colaborador')
          .filter(data__gte=inicio, data__lte=fim).order_by('data', 'hora_inicio'))
    if colaborador:
        qs = qs.filter(colaborador=colaborador)

    linhas, itens = {}, []
    for p in qs:
        h = _horas(p.hora_inicio, p.hora_fim)
        linhas.setdefault(p.colaborador_id, _Linha(p.colaborador.nome_completo)).somar(p.data, h)
        itens.append({
            'data': p.data, 'dia': DIAS[p.data.weekday()],
            'horario': f'{p.hora_inicio:%H:%M}–{p.hora_fim:%H:%M}',
            'tipo': p.get_turno_display(), 'pessoas': p.colaborador.nome_completo,
            'obs': p.observacoes or '',
        })

    resumo = sorted(linhas.values(), key=lambda l: (-l.horas, l.nome))
    alertas = escala.violacoes_no_periodo(inicio, fim) if itens else []
    if colaborador:
        alertas = [a for a in alertas if a.colaborador_id == colaborador.id]
    return {
        'area': 'sac', 'titulo': 'Relatório de plantões — SAC', 'rotulo_pessoa': 'Colaborador',
        'inicio': inicio, 'fim': fim, 'filtro_pessoa': colaborador.nome_completo if colaborador else '',
        'resumo': resumo, 'total': _totais(resumo), 'semanas': _agrupar_por_semana(itens),
        'quantidade': len(itens), 'alertas': [a.texto for a in alertas],
    }


def dados_tecnicos(inicio, fim, tecnico=None):
    qs = (PlantaoTecnico.objects.select_related('tecnico_principal', 'tecnico_dupla')
          .filter(data__gte=inicio, data__lte=fim).order_by('data', 'hora_inicio'))
    if tecnico:
        qs = qs.filter(Q(tecnico_principal=tecnico) | Q(tecnico_dupla=tecnico))

    linhas, itens = {}, []
    for p in qs:
        h = _horas(p.hora_inicio, p.hora_fim)
        envolvidos = [p.tecnico_principal] + ([p.tecnico_dupla] if p.tecnico_dupla else [])
        for t in envolvidos:
            if tecnico and t.id != tecnico.id:
                continue
            linhas.setdefault(t.id, _Linha(t.nome_completo)).somar(p.data, h)
        itens.append({
            'data': p.data, 'dia': DIAS[p.data.weekday()],
            'horario': f'{p.hora_inicio:%H:%M}–{p.hora_fim:%H:%M}',
            'tipo': p.get_tipo_display(),
            'pessoas': ' + '.join(t.nome_completo for t in envolvidos),
            'obs': p.observacoes or '',
        })

    resumo = sorted(linhas.values(), key=lambda l: (-l.horas, l.nome))
    return {
        'area': 'tecnicos', 'titulo': 'Relatório de plantões — Técnicos de campo',
        'rotulo_pessoa': 'Técnico', 'inicio': inicio, 'fim': fim,
        'filtro_pessoa': tecnico.nome_completo if tecnico else '',
        'resumo': resumo, 'total': _totais(resumo), 'semanas': _agrupar_por_semana(itens),
        'quantidade': len(itens), 'alertas': [],
    }


def pessoas_da_area(area):
    if area == 'tecnicos':
        return TecnicoCampo.objects.order_by('-ativo', 'nome_completo')
    return Colaborador.objects.order_by('-ativo', 'nome_completo')


# ─── PDF ────────────────────────────────────────────────────────────────────

COR = colors.HexColor('#E94920')
COR_TEXTO = colors.HexColor('#50443C')
COR_SUAVE = colors.HexColor('#9ca3af')
COR_ZEBRA = colors.HexColor('#fdf5f3')
COR_BORDA = colors.HexColor('#e5e7eb')
COR_FAIXA = colors.HexColor('#fff8f6')
COR_ALERTA = colors.HexColor('#fffbeb')
COR_ALERTA_TXT = colors.HexColor('#92400e')


def _estilo(nome, **kw):
    base = dict(fontName='Helvetica', fontSize=8, textColor=COR_TEXTO, leading=11)
    base.update(kw)
    return ParagraphStyle(nome, **base)


ST_TH = _estilo('th', fontName='Helvetica-Bold', textColor=colors.white, alignment=TA_CENTER)
ST_TD = _estilo('td')
ST_TDC = _estilo('tdc', alignment=TA_CENTER)
ST_TDR = _estilo('tdr', alignment=TA_RIGHT)
ST_TOT = _estilo('tot', fontName='Helvetica-Bold')
ST_TOTC = _estilo('totc', fontName='Helvetica-Bold', alignment=TA_CENTER)
ST_SECAO = _estilo('secao', fontName='Helvetica-Bold', fontSize=11, textColor=COR, leading=14,
                   spaceBefore=6, spaceAfter=6)


def _p(texto, estilo=ST_TD):
    return Paragraph(escape(str(texto)), estilo)


def _rodape(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(COR_BORDA)
    canvas.setLineWidth(0.4)
    y = doc.bottomMargin - 0.5 * cm
    canvas.line(doc.leftMargin, y, doc.leftMargin + doc.width, y)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(COR_SUAVE)
    canvas.drawString(doc.leftMargin, y - 0.35 * cm,
                      f"Rapidin Plantões — gerado em {timezone.localtime():%d/%m/%Y às %H:%M}")
    canvas.drawRightString(doc.leftMargin + doc.width, y - 0.35 * cm, f"Página {canvas.getPageNumber()}")
    canvas.restoreState()


def _tabela(linhas, larguras, estilos_extras=()):
    t = Table(linhas, colWidths=larguras, repeatRows=1)
    zebra = [('BACKGROUND', (0, i), (-1, i), colors.white if i % 2 else COR_ZEBRA)
             for i in range(1, len(linhas))]
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COR),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, COR_BORDA),
        *zebra, *estilos_extras,
    ]))
    return t


def gerar_pdf(dados, detalhado=True):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.6 * cm, bottomMargin=2.2 * cm,
                            title=dados['titulo'], author='Rapidin Plantões')
    W = doc.width
    el = []

    # Cabeçalho
    sub = f"Período: {dados['inicio']:%d/%m/%Y} a {dados['fim']:%d/%m/%Y}"
    if dados['filtro_pessoa']:
        sub += f" · {dados['rotulo_pessoa']}: {dados['filtro_pessoa']}"
    cab = Table([
        [Paragraph(f"<b>{escape(dados['titulo'])}</b>",
                   _estilo('h1', fontName='Helvetica-Bold', fontSize=14, textColor=colors.white, leading=18))],
        [Paragraph(escape(sub), _estilo('h2', fontSize=8.5, textColor=colors.white, leading=11))],
    ], colWidths=[W])
    cab.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COR),
        ('LEFTPADDING', (0, 0), (-1, -1), 14), ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, 0), 12), ('BOTTOMPADDING', (0, -1), (-1, -1), 12),
        ('TOPPADDING', (0, 1), (-1, 1), 0),
    ]))
    el += [cab, Spacer(1, 0.4 * cm)]

    # Indicadores
    total = dados['total']
    ind = [('Plantões', dados['quantidade']), ('Horas', total.horas_fmt),
           ('Fins de semana', total.fins_de_semana), ('Pessoas', len(dados['resumo']))]
    st_num = _estilo('num', fontName='Helvetica-Bold', fontSize=15, alignment=TA_CENTER, leading=18)
    st_lab = _estilo('lab', fontSize=7, textColor=COR_SUAVE, alignment=TA_CENTER)
    kpis = Table([[Paragraph(str(v), st_num) for _, v in ind],
                  [Paragraph(rot.upper(), st_lab) for rot, _ in ind]], colWidths=[W / 4] * 4)
    kpis.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.4, COR_BORDA),
        ('LINEAFTER', (0, 0), (-2, -1), 0.4, COR_BORDA),
        ('TOPPADDING', (0, 0), (-1, 0), 9), ('BOTTOMPADDING', (0, -1), (-1, -1), 9),
    ]))
    el += [kpis, Spacer(1, 0.5 * cm)]

    if not dados['quantidade']:
        el.append(Paragraph('Nenhum plantão encontrado neste período.',
                            _estilo('vazio', fontSize=10, textColor=COR_SUAVE, alignment=TA_CENTER)))
        doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
        return buffer.getvalue()

    # Resumo por pessoa
    el.append(Paragraph(f"Resumo por {dados['rotulo_pessoa'].lower()}", ST_SECAO))
    cab_res = [dados['rotulo_pessoa'], 'Plantões', 'Fins de sem.', 'Sáb', 'Dom', 'Avulsos', 'Horas']
    linhas = [[Paragraph(c, ST_TH) for c in cab_res]]
    for l in dados['resumo']:
        linhas.append([_p(l.nome), _p(l.plantoes, ST_TDC), _p(l.fins_de_semana, ST_TDC),
                       _p(l.sabados, ST_TDC), _p(l.domingos, ST_TDC), _p(l.avulsos, ST_TDC),
                       _p(l.horas_fmt, ST_TDC)])
    linhas.append([_p('Total', ST_TOT), _p(total.plantoes, ST_TOTC), _p(total.fins_de_semana, ST_TOTC),
                   _p(total.sabados, ST_TOTC), _p(total.domingos, ST_TOTC), _p(total.avulsos, ST_TOTC),
                   _p(total.horas_fmt, ST_TOTC)])
    el.append(_tabela(linhas, [W - 6 * 1.9 * cm] + [1.9 * cm] * 6, [
        ('BACKGROUND', (0, -1), (-1, -1), COR_FAIXA),
        ('LINEABOVE', (0, -1), (-1, -1), 0.8, COR),
    ]))

    # Alertas de regra
    if dados['alertas']:
        el.append(Spacer(1, 0.4 * cm))
        el.append(Paragraph('Alertas de regra da escala', ST_SECAO))
        st_al = _estilo('al', textColor=COR_ALERTA_TXT)
        caixa = Table([[Paragraph('• ' + escape(a), st_al)] for a in dados['alertas']], colWidths=[W])
        caixa.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COR_ALERTA),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#fcd34d')),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        el.append(caixa)

    # Detalhamento
    if detalhado:
        el.append(Spacer(1, 0.4 * cm))
        el.append(Paragraph('Plantões do período', ST_SECAO))
        larg = [2.1 * cm, 1.2 * cm, 2.3 * cm, 3.6 * cm, W - 13.0 * cm, 3.8 * cm]
        for semana in dados['semanas']:
            faixa = Paragraph(
                f"<b>Semana de {semana['inicio']:%d/%m} a {semana['fim']:%d/%m/%Y}</b>",
                _estilo('sem', fontName='Helvetica-Bold', fontSize=8.5, textColor=COR))
            faixa_t = Table([[faixa]], colWidths=[W])
            faixa_t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), COR_FAIXA),
                ('LINEBELOW', (0, 0), (-1, -1), 1, COR),
                ('LEFTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            cab_det = ['Data', 'Dia', 'Horário', 'Turno', dados['rotulo_pessoa'], 'Observações']
            linhas = [[Paragraph(c, ST_TH) for c in cab_det]]
            for i in semana['itens']:
                obs = i['obs'] if len(i['obs']) <= 60 else i['obs'][:59] + '…'
                linhas.append([_p(f"{i['data']:%d/%m/%Y}", ST_TDC), _p(i['dia'], ST_TDC),
                               _p(i['horario'], ST_TDC), _p(i['tipo']), _p(i['pessoas']),
                               _p(obs or '—')])
            el.append(KeepTogether([faixa_t, _tabela(linhas, larg)]))
            el.append(Spacer(1, 0.35 * cm))

    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    return buffer.getvalue()

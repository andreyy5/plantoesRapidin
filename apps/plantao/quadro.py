"""
Quadro do NOC: um quadro "neon" compartilhado onde qualquer usuário escreve
avisos (rompimentos de rota, SIUs fora...) e desenha com o mouse, e tudo
aparece para todos.

Tempo real por consulta periódica (polling): o servidor roda gunicorn com
worker síncrono e SQLite, então não usamos WebSocket. Todas as páginas do
sistema consultam `quadro/novidades/` a cada poucos segundos (ver
templates/partials/quadro_ao_vivo.html); a resposta é pequena quando nada mudou.

Os traços do desenho nunca mudam depois de criados. O estado do quadro traz só
os ids dos traços ativos; o navegador busca em `quadro/tracos/` apenas os que
ainda não conhece, para não reenviar o desenho inteiro a cada traço novo.
"""
import hashlib
import json
from datetime import timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import AlertaQuadro, AnotacaoQuadro, PresencaUsuario, TracoQuadro

MAX_LINHAS = 40
MAX_TRACOS = 600
MAX_PONTOS_POR_TRACO = 2000
LARGURA = TracoQuadro.UNIDADES_POR_LARGURA
ALTURA_MAXIMA = LARGURA * 4  # o quadro cresce para baixo, mas com limite
# Quem consultou o servidor nesse intervalo conta como conectado
JANELA_CONECTADO = timedelta(seconds=60)
# A presença só é gravada de tempos em tempos (evita escrita no banco a cada consulta)
GRAVAR_PRESENCA_A_CADA = timedelta(seconds=20)
# Avisos mais antigos que isso não aparecem para quem acabou de entrar
VALIDADE_ALERTA = timedelta(minutes=10)
# Intervalo mínimo entre dois avisos (evita clique duplo e avisos em sequência)
INTERVALO_ENTRE_ALERTAS = timedelta(seconds=15)
# Linhas e traços apagados ficam guardados por um tempo (para "Desfazer") e depois são removidos
GUARDAR_APAGADOS = timedelta(days=30)

_CORES = {c for c, _ in AnotacaoQuadro.CORES}


# ---------- utilitários ----------

def _login_json(view):
    """Como @login_required, mas responde 401 em JSON (as chamadas são feitas por fetch)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'erro': 'Sua sessão expirou. Entre de novo.'}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _erro(mensagem, status=400):
    return JsonResponse({'erro': mensagem}, status=status)


def _dados(request):
    try:
        dados = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _ids(valor):
    """Lista de ids inteiros a partir do que veio no JSON (ignora o resto)."""
    if not isinstance(valor, list):
        return []
    return [i for i in valor if isinstance(i, int) and not isinstance(i, bool)]


def _nome(user):
    if user is None:
        return 'Alguém'
    return user.get_full_name().strip() or user.username


def _hora(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _ativas():
    return AnotacaoQuadro.objects.filter(apagado_em__isnull=True)


def _tracos_ativos():
    return TracoQuadro.objects.filter(apagado_em__isnull=True)


def _limpar_texto(valor):
    """Uma linha só, sem espaços sobrando."""
    return ' '.join(str(valor or '').split())


def _pontos_validos(pontos):
    """Confere o formato [x, y, x, y, ...] e os limites. Devolve a lista ou None."""
    if not isinstance(pontos, list) or len(pontos) < 2 or len(pontos) % 2:
        return None
    if len(pontos) > MAX_PONTOS_POR_TRACO * 2:
        return None
    for i, v in enumerate(pontos):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return None
        if v > (LARGURA if i % 2 == 0 else ALTURA_MAXIMA):
            return None
    if len(pontos) == 2:  # um clique sem arrastar vira um ponto
        pontos = pontos * 2
    return pontos


# ---------- estado do quadro ----------

def _versao():
    """Muda sempre que algo é escrito, editado, desenhado ou apagado, ou quando sai um aviso."""
    linhas = list(_ativas().values_list('id', 'atualizado_em'))
    tracos = list(_tracos_ativos().values_list('id', flat=True))
    ultimo_alerta = AlertaQuadro.objects.values_list('id', flat=True).first() or 0
    bruto = repr((linhas, tracos, ultimo_alerta)).encode()
    return hashlib.md5(bruto, usedforsecurity=False).hexdigest()[:16]


def _anotacao_json(a):
    return {
        'id': a.id,
        'texto': a.texto,
        'cor': a.cor,
        'autor': _nome(a.criado_por),
        'criado_em': _hora(a.criado_em),
        'editado_por': _nome(a.editado_por) if a.editado_em else None,
        'editado_em': _hora(a.editado_em),
    }


def _traco_json(t):
    return {'id': t.id, 'cor': t.cor, 'pontos': t.pontos}


def _alerta_json(a, com_desenho=True):
    dados = {
        'id': a.id,
        'linhas': a.linhas,
        'tem_desenho': bool(a.tracos),
        'autor': _nome(a.criado_por),
        'autor_id': a.criado_por_id,
        'criado_em': _hora(a.criado_em),
    }
    if com_desenho:
        dados['tracos'] = a.tracos
    return dados


def _estado():
    anotacoes = _ativas().select_related('criado_por', 'editado_por')
    avisos = AlertaQuadro.objects.select_related('criado_por')[:5]
    return {
        'versao': _versao(),
        'anotacoes': [_anotacao_json(a) for a in anotacoes],
        'tracos': list(_tracos_ativos().values_list('id', flat=True)),
        'avisos': [_alerta_json(a, com_desenho=False) for a in avisos],
    }


def _conectados(request):
    desde = timezone.now() - JANELA_CONECTADO
    presencas = (
        PresencaUsuario.objects.filter(visto_em__gte=desde, user__is_active=True)
        .select_related('user').order_by('user__first_name', 'user__username')
    )
    return [
        {'id': p.user_id, 'nome': _nome(p.user), 'voce': p.user_id == request.user.id}
        for p in presencas
    ]


def _marcar_presenca(user):
    agora = timezone.now()
    gravou = PresencaUsuario.objects.filter(
        user=user, visto_em__lt=agora - GRAVAR_PRESENCA_A_CADA
    ).update(visto_em=agora)
    if not gravou:
        PresencaUsuario.objects.get_or_create(user=user, defaults={'visto_em': agora})


def _resposta_com_estado(request, **extra):
    return JsonResponse({'quadro': _estado(), 'conectados': _conectados(request), **extra})


def _faxina(agora):
    """Remove de vez o que foi apagado há muito tempo (não precisa mais de "Desfazer")."""
    limite = agora - GUARDAR_APAGADOS
    AnotacaoQuadro.objects.filter(apagado_em__lt=limite).delete()
    TracoQuadro.objects.filter(apagado_em__lt=limite).delete()


# ---------- páginas e chamadas ----------

@login_required
def quadro(request):
    """Página do quadro. Acessível a qualquer usuário logado (SAC, técnicos, NOC)."""
    _marcar_presenca(request.user)
    return render(request, 'dashboard/quadro.html', {
        'estado_inicial': {
            **_estado(),
            'conectados': _conectados(request),
            'dados_tracos': [_traco_json(t) for t in _tracos_ativos()],
        },
        'cores': AnotacaoQuadro.CORES,
        'max_texto': AnotacaoQuadro.MAX_TEXTO,
    })


@require_GET
@_login_json
def novidades(request):
    """
    Consulta periódica feita por todas as páginas.

    ?alerta=<id>  último aviso que este navegador já viu. Sem ele, só devolve o id
                  do último aviso (quem acabou de abrir o sistema não recebe aviso antigo).
    ?versao=<v>   enviado só pela página do quadro; se o quadro mudou, devolve o estado novo.
    """
    _marcar_presenca(request.user)
    ultimo_id = AlertaQuadro.objects.values_list('id', flat=True).first() or 0
    resposta = {
        'ultimo_alerta': ultimo_id,
        'alerta': None,
        'linhas_no_quadro': _ativas().count(),
        'tem_desenho': _tracos_ativos().exists(),
    }

    visto = request.GET.get('alerta', '')
    if visto.isdigit() and int(visto) < ultimo_id:
        novo = (
            AlertaQuadro.objects
            .filter(id__gt=int(visto), criado_em__gte=timezone.now() - VALIDADE_ALERTA)
            .exclude(criado_por=request.user)
            .select_related('criado_por')
            .first()  # o mais recente
        )
        if novo:
            resposta['alerta'] = _alerta_json(novo)

    if 'versao' in request.GET:
        resposta['conectados'] = _conectados(request)
        if request.GET['versao'] != _versao():
            resposta['quadro'] = _estado()
    return JsonResponse(resposta)


@require_GET
@_login_json
def tracos(request):
    """Dados dos traços pedidos (?ids=1,2,3), inclusive apagados (para o "Desfazer" de outra pessoa)."""
    ids = [int(i) for i in request.GET.get('ids', '').split(',') if i.isdigit()][:MAX_TRACOS]
    return JsonResponse({'tracos': [_traco_json(t) for t in TracoQuadro.objects.filter(id__in=ids)]})


@require_POST
@_login_json
def escrever(request):
    dados = _dados(request)
    texto = _limpar_texto(dados.get('texto'))
    cor = dados.get('cor') if dados.get('cor') in _CORES else 'rosa'
    if not texto:
        return _erro('Escreva alguma coisa antes de salvar.')
    if len(texto) > AnotacaoQuadro.MAX_TEXTO:
        return _erro(f'Use no máximo {AnotacaoQuadro.MAX_TEXTO} caracteres por linha.')
    if _ativas().count() >= MAX_LINHAS:
        return _erro(f'O quadro está cheio ({MAX_LINHAS} linhas). Apague o que já foi resolvido.')
    nova = AnotacaoQuadro.objects.create(texto=texto, cor=cor, criado_por=request.user)
    return _resposta_com_estado(request, id=nova.id)


@require_POST
@_login_json
def editar(request, anotacao_id):
    anotacao = _ativas().filter(id=anotacao_id).first()
    if anotacao is None:
        return _erro('Essa linha já foi apagada por outra pessoa.', status=404)
    dados = _dados(request)
    if 'texto' in dados:
        texto = _limpar_texto(dados.get('texto'))
        if not texto:
            return _erro('A linha não pode ficar vazia. Para tirar do quadro, use Apagar.')
        if len(texto) > AnotacaoQuadro.MAX_TEXTO:
            return _erro(f'Use no máximo {AnotacaoQuadro.MAX_TEXTO} caracteres por linha.')
        anotacao.texto = texto
    if dados.get('cor') in _CORES:
        anotacao.cor = dados['cor']
    anotacao.editado_por, anotacao.editado_em = request.user, timezone.now()
    anotacao.save()
    return _resposta_com_estado(request)


@require_POST
@_login_json
def apagar(request, anotacao_id):
    agora = timezone.now()
    with transaction.atomic():
        apagadas = _ativas().filter(id=anotacao_id).update(
            apagado_em=agora, apagado_por=request.user, atualizado_em=agora
        )
        _faxina(agora)
    return _resposta_com_estado(request, apagadas=[anotacao_id] if apagadas else [])


@require_POST
@_login_json
def desenhar(request):
    """Grava um traço feito à mão."""
    dados = _dados(request)
    pontos = _pontos_validos(dados.get('pontos'))
    if pontos is None:
        return _erro('Não foi possível salvar o desenho. Tente de novo.')
    if _tracos_ativos().count() >= MAX_TRACOS:
        return _erro('O quadro está cheio de desenhos. Use o apagador ou limpe o quadro.')
    cor = dados.get('cor') if dados.get('cor') in _CORES else 'rosa'
    traco = TracoQuadro.objects.create(cor=cor, pontos=pontos, criado_por=request.user)
    return _resposta_com_estado(request, id=traco.id)


@require_POST
@_login_json
def apagar_tracos(request):
    agora = timezone.now()
    ids = _ids(_dados(request).get('ids'))
    with transaction.atomic():
        apagados = list(_tracos_ativos().filter(id__in=ids).values_list('id', flat=True))
        TracoQuadro.objects.filter(id__in=apagados).update(apagado_em=agora, apagado_por=request.user)
        _faxina(agora)
    return _resposta_com_estado(request, tracos_apagados=apagados)


@require_POST
@_login_json
def limpar(request):
    agora = timezone.now()
    with transaction.atomic():
        ids = list(_ativas().values_list('id', flat=True))
        AnotacaoQuadro.objects.filter(id__in=ids).update(
            apagado_em=agora, apagado_por=request.user, atualizado_em=agora
        )
        tracos_ids = list(_tracos_ativos().values_list('id', flat=True))
        TracoQuadro.objects.filter(id__in=tracos_ids).update(apagado_em=agora, apagado_por=request.user)
    return _resposta_com_estado(request, apagadas=ids, tracos_apagados=tracos_ids)


@require_POST
@_login_json
def restaurar(request):
    """Desfaz "Apagar", o apagador de desenhos e "Limpar quadro"."""
    dados = _dados(request)
    ids, tracos_ids = _ids(dados.get('ids')), _ids(dados.get('tracos'))
    if len(ids) > MAX_LINHAS - _ativas().count() or len(tracos_ids) > MAX_TRACOS - _tracos_ativos().count():
        return _erro('Não cabe tudo de volta: o quadro já está cheio.')
    agora = timezone.now()
    with transaction.atomic():
        AnotacaoQuadro.objects.filter(id__in=ids, apagado_em__isnull=False).update(
            apagado_em=None, apagado_por=None, atualizado_em=agora
        )
        TracoQuadro.objects.filter(id__in=tracos_ids, apagado_em__isnull=False).update(
            apagado_em=None, apagado_por=None
        )
    return _resposta_com_estado(request)


@require_POST
@_login_json
def avisar(request):
    """
    Dispara o aviso. `ids`: linhas escolhidas (todas, se não vier); `desenho`: se
    inclui os desenhos (sim, se não vier). O texto é lido em voz alta; o desenho só aparece.
    """
    agora = timezone.now()
    dados = _dados(request)
    with transaction.atomic():
        ultimo = AlertaQuadro.objects.select_related('criado_por').first()
        if ultimo and agora - ultimo.criado_em < INTERVALO_ENTRE_ALERTAS:
            quem = 'Você' if ultimo.criado_por_id == request.user.id else _nome(ultimo.criado_por)
            return _erro(f'{quem} acabou de enviar um aviso. Aguarde alguns segundos.', status=429)

        anotacoes = _ativas()
        if 'ids' in dados:
            anotacoes = anotacoes.filter(id__in=_ids(dados['ids']))
        linhas = [{'texto': a.texto, 'cor': a.cor} for a in anotacoes]
        desenho = []
        if dados.get('desenho', True):
            desenho = [{'cor': t.cor, 'pontos': t.pontos} for t in _tracos_ativos()]
        if not linhas and not desenho:
            return _erro('Não há nada no quadro para avisar.')
        alerta = AlertaQuadro.objects.create(linhas=linhas, tracos=desenho, criado_por=request.user)

    outros = [c for c in _conectados(request) if not c['voce']]
    return _resposta_com_estado(request, alerta=_alerta_json(alerta), avisados=len(outros))

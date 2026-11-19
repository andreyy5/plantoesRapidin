"""
Quadro do NOC: um quadro "neon" compartilhado onde qualquer usuário escreve
avisos (rompimentos de rota, SIUs fora...) que aparecem para todos.

Tempo real por consulta periódica (polling): o servidor roda gunicorn com
worker síncrono e SQLite, então não usamos WebSocket. Todas as páginas do
sistema consultam `quadro/novidades/` a cada poucos segundos (ver
templates/partials/quadro_ao_vivo.html); a resposta é pequena quando nada mudou.
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

from .models import AlertaQuadro, AnotacaoQuadro, PresencaUsuario

MAX_LINHAS = 40
# Quem consultou o servidor nesse intervalo conta como conectado
JANELA_CONECTADO = timedelta(seconds=60)
# A presença só é gravada de tempos em tempos (evita escrita no banco a cada consulta)
GRAVAR_PRESENCA_A_CADA = timedelta(seconds=20)
# Avisos mais antigos que isso não aparecem para quem acabou de entrar
VALIDADE_ALERTA = timedelta(minutes=10)
# Intervalo mínimo entre dois avisos (evita clique duplo e avisos em sequência)
INTERVALO_ENTRE_ALERTAS = timedelta(seconds=15)
# Linhas apagadas ficam guardadas por um tempo (para "Desfazer") e depois são removidas
GUARDAR_APAGADAS = timedelta(days=30)

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


def _nome(user):
    if user is None:
        return 'Alguém'
    return user.get_full_name().strip() or user.username


def _hora(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _ativas():
    return AnotacaoQuadro.objects.filter(apagado_em__isnull=True)


def _limpar_texto(valor):
    """Uma linha só, sem espaços sobrando."""
    return ' '.join(str(valor or '').split())


# ---------- estado do quadro ----------

def _versao():
    """Muda sempre que uma linha é escrita, editada ou apagada, ou quando sai um aviso."""
    linhas = list(_ativas().values_list('id', 'atualizado_em'))
    ultimo_alerta = AlertaQuadro.objects.values_list('id', flat=True).first() or 0
    bruto = repr((linhas, ultimo_alerta)).encode()
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


def _alerta_json(a):
    return {
        'id': a.id,
        'linhas': a.linhas,
        'autor': _nome(a.criado_por),
        'autor_id': a.criado_por_id,
        'criado_em': _hora(a.criado_em),
    }


def _estado():
    anotacoes = _ativas().select_related('criado_por', 'editado_por')
    avisos = AlertaQuadro.objects.select_related('criado_por')[:5]
    return {
        'versao': _versao(),
        'anotacoes': [_anotacao_json(a) for a in anotacoes],
        'avisos': [_alerta_json(a) for a in avisos],
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


# ---------- páginas e chamadas ----------

@login_required
def quadro(request):
    """Página do quadro. Acessível a qualquer usuário logado (SAC, técnicos, NOC)."""
    _marcar_presenca(request.user)
    return render(request, 'dashboard/quadro.html', {
        'estado_inicial': {**_estado(), 'conectados': _conectados(request)},
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
        # Faxina: linhas apagadas há muito tempo não precisam mais de "Desfazer"
        AnotacaoQuadro.objects.filter(apagado_em__lt=agora - GUARDAR_APAGADAS).delete()
    return _resposta_com_estado(request, apagadas=[anotacao_id] if apagadas else [])


@require_POST
@_login_json
def limpar(request):
    agora = timezone.now()
    with transaction.atomic():
        ids = list(_ativas().values_list('id', flat=True))
        AnotacaoQuadro.objects.filter(id__in=ids).update(
            apagado_em=agora, apagado_por=request.user, atualizado_em=agora
        )
    return _resposta_com_estado(request, apagadas=ids)


@require_POST
@_login_json
def restaurar(request):
    """Desfaz "Apagar" e "Limpar quadro"."""
    ids = [i for i in _dados(request).get('ids', []) if isinstance(i, int)]
    vagas = MAX_LINHAS - _ativas().count()
    if len(ids) > vagas:
        return _erro('Não cabe tudo de volta: o quadro já está cheio.')
    AnotacaoQuadro.objects.filter(id__in=ids, apagado_em__isnull=False).update(
        apagado_em=None, apagado_por=None, atualizado_em=timezone.now()
    )
    return _resposta_com_estado(request)


@require_POST
@_login_json
def avisar(request):
    """Dispara o aviso com as linhas escolhidas (todas, se nenhuma for informada)."""
    agora = timezone.now()
    with transaction.atomic():
        ultimo = AlertaQuadro.objects.select_related('criado_por').first()
        if ultimo and agora - ultimo.criado_em < INTERVALO_ENTRE_ALERTAS:
            quem = 'Você' if ultimo.criado_por_id == request.user.id else _nome(ultimo.criado_por)
            return _erro(f'{quem} acabou de enviar um aviso. Aguarde alguns segundos.', status=429)

        anotacoes = _ativas()
        ids = _dados(request).get('ids')
        if isinstance(ids, list) and ids:
            anotacoes = anotacoes.filter(id__in=[i for i in ids if isinstance(i, int)])
        linhas = [{'texto': a.texto, 'cor': a.cor} for a in anotacoes]
        if not linhas:
            return _erro('Não há nada escrito no quadro para avisar.')
        alerta = AlertaQuadro.objects.create(linhas=linhas, criado_por=request.user)

    outros = [c for c in _conectados(request) if not c['voce']]
    return _resposta_com_estado(request, alerta=_alerta_json(alerta), avisados=len(outros))

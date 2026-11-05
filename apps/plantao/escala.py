"""
Regras e geração automática da escala de plantões do SAC.

Regras obrigatórias
-------------------
1. Quem fez o último plantão do domingo (17h–21h) não abre a semana seguinte
   (sábado 13h–17h).
2. Ninguém trabalha mais que MAX_DIAS_SEGUIDOS dias seguidos. Na contagem, o
   atendente trabalha normalmente nos DIAS_EXPEDIENTE (segunda a sábado; o
   sábado é expediente até 12h); o domingo só conta quando ele tem plantão.
   Na prática: ninguém pega plantão em dois domingos seguidos (daria 20 dias).

Critérios de distribuição (em ordem de prioridade)
--------------------------------------------------
1. Plantões afastados: evita escalar quem trabalhou nos fins de semana mais
   recentes (quanto mais recente, maior o peso).
2. Equilíbrio: prioriza quem fez menos horas de plantão nas últimas semanas, e
   os turnos mais longos vão para quem está com menos horas.
3. Ordem da fila: em caso de empate, vai primeiro quem está há mais tempo sem
   plantão e, depois, a ordem cadastrada na fila.
"""

from collections import defaultdict, namedtuple
from dataclasses import dataclass
from datetime import date, time, timedelta
from itertools import permutations

from django.db import transaction

from .models import Colaborador, EscalaAutomatica, Plantao


MAX_DIAS_SEGUIDOS = 14

# Dias em que o atendente trabalha normalmente, sem plantão (0 = segunda).
# Sábado é expediente normal até 12h, por isso entra na conta.
DIAS_EXPEDIENTE = frozenset({0, 1, 2, 3, 4, 5})

# Os 3 plantonistas de cada fim de semana trabalham no domingo, e dois domingos
# seguidos passam do limite. Logo, quem trabalha num fim de semana folga no
# seguinte: são necessários 2 grupos de 3 atendentes.
MIN_COLABORADORES = 6

TURNO_ABRE_SEMANA = 'SABADO_TARDE1'      # sábado 13h–17h
TURNO_FECHA_DOMINGO = 'DOMINGO_TARDE2'   # domingo 17h–21h

# Peso por fim de semana trabalhado recentemente: 1 semana atrás, 2, 3 e 4.
PESOS_DESCANSO = (16, 8, 4, 2)
SEMANAS_JANELA_CARGA = 8
LIMITE_TENTATIVAS = 20000


@dataclass(frozen=True)
class Papel:
    codigo: str
    turnos: tuple  # ((turno, dias após o sábado), ...)


PAPEIS = (
    Papel('A', (('SABADO_TARDE1', 0), ('DOMINGO_TARDE1', 1))),
    Papel('B', (('SABADO_TARDE2', 0), ('DOMINGO_MANHA', 1))),
    Papel('C', (('DOMINGO_TARDE2', 1),)),
)
TURNOS_FIM_DE_SEMANA = tuple(t for p in PAPEIS for t, _ in p.turnos)

Registro = namedtuple('Registro', 'id colaborador_id data turno')


class EscalaImpossivel(Exception):
    """Não há como montar a escala respeitando as regras."""


@dataclass(frozen=True)
class Violacao:
    tipo: str
    colaborador_id: int
    inicio: date
    fim: date
    texto: str

    @property
    def chave(self):
        return (self.tipo, self.colaborador_id, self.inicio, self.fim)


# ─── Utilitários ────────────────────────────────────────────────────────────

def horas_turno(turno):
    inicio, fim = Plantao.get_horarios_por_turno(turno)
    if not inicio:
        return 0
    return (fim.hour * 60 + fim.minute - inicio.hour * 60 - inicio.minute) / 60


HORAS_PAPEL = {p.codigo: sum(horas_turno(t) for t, _ in p.turnos) for p in PAPEIS}


def sabado_do_fim_de_semana(dia):
    """Sábado do fim de semana a que a data pertence (None em dia útil)."""
    if dia.weekday() == 5:
        return dia
    if dia.weekday() == 6:
        return dia - timedelta(days=1)
    return None


def proximo_sabado(dia):
    """Primeiro sábado estritamente depois de `dia`."""
    return dia + timedelta(days=(5 - dia.weekday()) % 7 or 7)


def _trabalha(dia, datas_plantao):
    return dia.weekday() in DIAS_EXPEDIENTE or dia in datas_plantao


def sequencia(dia, datas_plantao, limite=400):
    """Período (início, fim) de dias seguidos trabalhados que contém `dia`."""
    if not _trabalha(dia, datas_plantao):
        return None
    inicio = fim = dia
    for _ in range(limite):
        if not _trabalha(inicio - timedelta(days=1), datas_plantao):
            break
        inicio -= timedelta(days=1)
    for _ in range(limite):
        if not _trabalha(fim + timedelta(days=1), datas_plantao):
            break
        fim += timedelta(days=1)
    return inicio, fim


def _dias(periodo):
    return (periodo[1] - periodo[0]).days + 1


def _fmt(dia):
    return dia.strftime('%d/%m/%Y')


# ─── Análise de uma escala existente ────────────────────────────────────────

def analisar(registros, nomes):
    """Lista as violações de regra em um conjunto de plantões."""
    nome = lambda cid: nomes.get(cid, f'Colaborador #{cid}')
    violacoes = []

    datas_por_colab = defaultdict(set)
    for r in registros:
        datas_por_colab[r.colaborador_id].add(r.data)

    for cid, datas in datas_por_colab.items():
        vistos = set()
        for dia in sorted(datas):
            if dia.weekday() in DIAS_EXPEDIENTE:
                continue  # plantão em dia útil não muda a sequência
            periodo = sequencia(dia, datas)
            if periodo in vistos:
                continue
            vistos.add(periodo)
            if _dias(periodo) > MAX_DIAS_SEGUIDOS:
                violacoes.append(Violacao(
                    'DIAS_SEGUIDOS', cid, periodo[0], periodo[1],
                    f'{nome(cid)} fica {_dias(periodo)} dias seguidos trabalhando '
                    f'({_fmt(periodo[0])} a {_fmt(periodo[1])}). '
                    f'O máximo é {MAX_DIAS_SEGUIDOS}.'
                ))

    fecha = {r.data: r.colaborador_id for r in registros if r.turno == TURNO_FECHA_DOMINGO}
    for r in registros:
        if r.turno != TURNO_ABRE_SEMANA:
            continue
        domingo_anterior = r.data - timedelta(days=6)
        if fecha.get(domingo_anterior) == r.colaborador_id:
            violacoes.append(Violacao(
                'ABRE_APOS_FECHAR', r.colaborador_id, domingo_anterior, r.data,
                f'{nome(r.colaborador_id)} fechou o domingo {_fmt(domingo_anterior)} '
                f'(17h–21h) e abre a semana seguinte no sábado {_fmt(r.data)} (13h–17h).'
            ))

    return sorted(violacoes, key=lambda v: (v.inicio, v.texto))


# ─── Geração ────────────────────────────────────────────────────────────────

class _Gerador:
    def __init__(self, colaboradores, data_inicio, semanas, registros):
        self.colaboradores = list(colaboradores)
        self.ordem = {cid: i for i, cid in enumerate(self.colaboradores)}
        self.data_inicio = data_inicio
        self.semanas = semanas
        self.tentativas = 0

        inicio_carga = data_inicio - timedelta(weeks=SEMANAS_JANELA_CARGA)
        self.datas = {cid: set() for cid in self.colaboradores}
        self.fds = {cid: set() for cid in self.colaboradores}
        self.horas = {cid: 0.0 for cid in self.colaboradores}
        self.ultimo = {cid: (date.min, time.min) for cid in self.colaboradores}
        self.fecha = {}   # domingo -> quem fez o 17h–21h
        self.abre = {}    # sábado  -> quem fez o 13h–17h

        for r in registros:
            if r.turno == TURNO_FECHA_DOMINGO:
                self.fecha[r.data] = r.colaborador_id
            elif r.turno == TURNO_ABRE_SEMANA:
                self.abre[r.data] = r.colaborador_id
            cid = r.colaborador_id
            if cid not in self.datas:
                continue  # colaborador inativo
            self.datas[cid].add(r.data)
            if r.data >= data_inicio:
                continue
            sabado = sabado_do_fim_de_semana(r.data)
            if sabado:
                self.fds[cid].add(sabado)
            if r.data >= inicio_carga:
                self.horas[cid] += horas_turno(r.turno)
            fim = Plantao.get_horarios_por_turno(r.turno)[1] or time.min
            self.ultimo[cid] = max(self.ultimo[cid], (r.data, fim))

    # Estado ----------------------------------------------------------------
    def _estado(self):
        return (
            {c: set(v) for c, v in self.datas.items()},
            {c: set(v) for c, v in self.fds.items()},
            dict(self.horas), dict(self.ultimo), dict(self.fecha),
        )

    def _restaurar(self, estado):
        self.datas, self.fds, self.horas, self.ultimo, self.fecha = estado

    def _aplicar(self, sabado, escolha):
        domingo = sabado + timedelta(days=1)
        for papel, cid in zip(PAPEIS, escolha):
            for turno, offset in papel.turnos:
                self.datas[cid].add(sabado + timedelta(days=offset))
            self.fds[cid].add(sabado)
            self.horas[cid] += HORAS_PAPEL[papel.codigo]
            ultimo_turno = papel.turnos[-1][0]
            self.ultimo[cid] = (domingo, Plantao.get_horarios_por_turno(ultimo_turno)[1])
        self.fecha[domingo] = escolha[-1]

    # Regras ----------------------------------------------------------------
    def _cabe(self, cid, novas_datas):
        datas = self.datas[cid] | set(novas_datas)
        return all(_dias(sequencia(d, datas)) <= MAX_DIAS_SEGUIDOS for d in novas_datas)

    def _opcoes(self, sabado):
        domingo = sabado + timedelta(days=1)
        fechou_antes = self.fecha.get(sabado - timedelta(days=6))  # domingo anterior
        abre_depois = self.abre.get(sabado + timedelta(days=7))
        pode_fds = {c for c in self.colaboradores if self._cabe(c, (sabado, domingo))}
        pode_dom = {c for c in self.colaboradores if self._cabe(c, (domingo,))}

        for a, b, c in permutations(self.colaboradores, 3):
            if a == fechou_antes or c == abre_depois:
                continue
            if a in pode_fds and b in pode_fds and c in pode_dom:
                yield a, b, c

    def _custo(self, sabado):
        def penalidade(cid):
            return sum(
                peso for k, peso in enumerate(PESOS_DESCANSO, start=1)
                if sabado - timedelta(weeks=k) in self.fds[cid]
            )

        fila = sorted(self.colaboradores, key=lambda c: (self.ultimo[c], self.ordem[c]))
        posicao = {cid: i for i, cid in enumerate(fila)}
        pen = {cid: penalidade(cid) for cid in self.colaboradores}

        def custo(escolha):
            return (
                sum(pen[c] for c in escolha),
                sum(self.horas[c] for c in escolha),
                sum(self.horas[c] * HORAS_PAPEL[p.codigo] for p, c in zip(PAPEIS, escolha)),
                tuple(posicao[c] for c in escolha),
            )
        return custo

    # Busca -----------------------------------------------------------------
    def _buscar(self, semana):
        if semana == self.semanas:
            return []
        sabado = self.data_inicio + timedelta(weeks=semana)
        for escolha in sorted(self._opcoes(sabado), key=self._custo(sabado)):
            self.tentativas += 1
            if self.tentativas > LIMITE_TENTATIVAS:
                break
            estado = self._estado()
            self._aplicar(sabado, escolha)
            resto = self._buscar(semana + 1)
            if resto is not None:
                return [(sabado, escolha)] + resto
            self._restaurar(estado)
        return None

    def gerar(self):
        if len(self.colaboradores) < MIN_COLABORADORES:
            raise EscalaImpossivel(
                f'São necessários pelo menos {MIN_COLABORADORES} colaboradores ativos '
                f'para cumprir a regra de {MAX_DIAS_SEGUIDOS} dias seguidos '
                f'(hoje há {len(self.colaboradores)}). '
                'Cadastre ou ative mais colaboradores.'
            )
        resultado = self._buscar(0)
        if resultado is None:
            raise EscalaImpossivel(
                'Não foi possível montar a escala respeitando as regras '
                f'(máximo de {MAX_DIAS_SEGUIDOS} dias seguidos e quem fecha o domingo '
                'não abre a semana seguinte) com os colaboradores ativos. '
                'Ative mais colaboradores ou gere menos semanas.'
            )
        return resultado


def gerar(colaboradores, data_inicio, semanas, registros):
    """
    Distribui os papéis A, B e C de cada fim de semana.

    colaboradores: ids na ordem da fila.
    registros: plantões já existentes (antes e depois do período).
    Retorna [(sabado, (id_A, id_B, id_C)), ...].
    """
    return _Gerador(colaboradores, data_inicio, semanas, registros).gerar()


def registros_da_escala(semanas_geradas):
    """Converte o resultado de `gerar` em registros de plantão."""
    registros = []
    for sabado, escolha in semanas_geradas:
        for papel, cid in zip(PAPEIS, escolha):
            for turno, offset in papel.turnos:
                registros.append(Registro(None, cid, sabado + timedelta(days=offset), turno))
    return registros


# ─── Integração com o banco ─────────────────────────────────────────────────

def carregar_registros(inicio, fim, excluir_ids=()):
    qs = Plantao.objects.filter(data__gte=inicio, data__lte=fim).exclude(id__in=excluir_ids)
    return [Registro(*v) for v in qs.values_list('id', 'colaborador_id', 'data', 'turno')]


def nomes_colaboradores():
    return dict(Colaborador.objects.values_list('id', 'nome_completo'))


def violacoes_no_periodo(inicio, fim):
    """Violações de regra que tocam o período [inicio, fim]."""
    margem = timedelta(weeks=5)
    registros = carregar_registros(inicio - margem, fim + margem)
    return [v for v in analisar(registros, nomes_colaboradores())
            if v.fim >= inicio and v.inicio <= fim]


def violacoes_novas(remover_ids=(), adicionar=()):
    """
    Violações que passariam a existir se os plantões `remover_ids` fossem
    retirados e os registros `adicionar` incluídos.
    """
    datas = [r.data for r in adicionar]
    if not datas:
        return []
    margem = timedelta(weeks=5)
    antes = carregar_registros(min(datas) - margem, max(datas) + margem)
    depois = [r for r in antes if r.id not in set(remover_ids)] + list(adicionar)
    nomes = nomes_colaboradores()
    existentes = {v.chave for v in analisar(antes, nomes)}
    return [v for v in analisar(depois, nomes) if v.chave not in existentes]


def datas_ocupadas(data_inicio, semanas):
    """Datas de fim de semana do período que já têm plantão cadastrado."""
    fim = data_inicio + timedelta(weeks=semanas - 1, days=1)
    datas = (
        Plantao.objects
        .filter(data__gte=data_inicio, data__lte=fim, data__week_day__in=(1, 7))
        .values_list('data', flat=True)
    )
    return sorted(set(datas))


@dataclass
class EscalaProposta:
    data_inicio: date
    semanas: int
    linhas: list      # [{'sabado', 'domingo', 'A', 'B', 'C'}] com objetos Colaborador
    resumo: list      # [{'colaborador', 'fins_de_semana', 'horas'}]
    registros: list

    @property
    def data_fim(self):
        return self.data_inicio + timedelta(weeks=self.semanas - 1, days=1)


def montar(data_inicio, semanas):
    """Monta (sem salvar) a escala proposta para o período."""
    ocupadas = datas_ocupadas(data_inicio, semanas)
    if ocupadas:
        lista = ', '.join(_fmt(d) for d in ocupadas[:6])
        if len(ocupadas) > 6:
            lista += f' e mais {len(ocupadas) - 6}'
        raise EscalaImpossivel(
            f'Já existem plantões de fim de semana neste período ({lista}). '
            'Escolha outra data de início ou remova esses plantões antes.'
        )

    colaboradores = list(Colaborador.objects.filter(ativo=True).order_by('ordem_fila', 'nome_completo'))
    por_id = {c.id: c for c in colaboradores}
    fim = data_inicio + timedelta(weeks=semanas)
    registros = carregar_registros(
        data_inicio - timedelta(weeks=SEMANAS_JANELA_CARGA), fim + timedelta(weeks=3)
    )
    semanas_geradas = gerar([c.id for c in colaboradores], data_inicio, semanas, registros)

    linhas = []
    for sabado, escolha in semanas_geradas:
        linha = {'sabado': sabado, 'domingo': sabado + timedelta(days=1)}
        linha.update({p.codigo: por_id[cid] for p, cid in zip(PAPEIS, escolha)})
        linhas.append(linha)

    resumo = []
    for c in colaboradores:
        horas = sum(
            HORAS_PAPEL[p.codigo]
            for _, escolha in semanas_geradas
            for p, cid in zip(PAPEIS, escolha) if cid == c.id
        )
        resumo.append({
            'colaborador': c,
            'fins_de_semana': sum(1 for _, escolha in semanas_geradas if c.id in escolha),
            'horas': horas,
        })

    return EscalaProposta(data_inicio, semanas, linhas, resumo,
                          registros_da_escala(semanas_geradas))


def salvar(proposta, usuario):
    """Grava a escala proposta. Tudo ou nada."""
    with transaction.atomic():
        if datas_ocupadas(proposta.data_inicio, proposta.semanas):
            raise EscalaImpossivel(
                'Outros plantões foram cadastrados neste período enquanto a escala '
                'era montada. Gere a pré-visualização novamente.'
            )
        EscalaAutomatica.objects.create(
            data_inicio=proposta.data_inicio,
            semanas_gerar=proposta.semanas,
            criada_por=usuario,
        )
        for r in proposta.registros:
            Plantao(colaborador_id=r.colaborador_id, data=r.data, turno=r.turno).save()
    return len(proposta.registros)

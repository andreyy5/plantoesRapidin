from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import escala
from .forms import PlantaoForm
from .models import Colaborador, EscalaAutomatica, Notificacao, Plantao, TrocaPlantao

R = escala.Registro
SAB = date(2026, 11, 7)  # um sábado


def _fim_de_semana(cid, sabado, papel):
    """Registros de um papel (A, B ou C) em um fim de semana."""
    p = next(p for p in escala.PAPEIS if p.codigo == papel)
    return [R(None, cid, sabado + timedelta(days=off), turno) for turno, off in p.turnos]


class RegrasTests(TestCase):
    def test_domingos_seguidos_passam_de_14_dias(self):
        # Sábado é expediente: seg–dom + seg–dom + seg–sáb = 20 dias
        regs = _fim_de_semana(1, SAB, 'C') + _fim_de_semana(1, SAB + timedelta(weeks=1), 'C')
        violacoes = escala.analisar(regs, {1: 'Ana'})
        self.assertEqual([v.tipo for v in violacoes], ['DIAS_SEGUIDOS'])
        self.assertIn('20 dias seguidos', violacoes[0].texto)

    def test_um_domingo_de_plantao_fica_dentro_do_limite(self):
        # seg–sáb + domingo + seg–sáb = 13 dias
        regs = _fim_de_semana(1, SAB, 'A')
        self.assertEqual(escala.analisar(regs, {1: 'Ana'}), [])

    def test_domingos_alternados_sao_permitidos(self):
        regs = _fim_de_semana(1, SAB, 'A') + _fim_de_semana(1, SAB + timedelta(weeks=2), 'B')
        self.assertEqual(escala.analisar(regs, {1: 'Ana'}), [])

    def test_plantao_so_no_sabado_nao_aumenta_a_sequencia(self):
        regs = _fim_de_semana(1, SAB, 'A') + [
            R(None, 1, SAB + timedelta(weeks=1), 'SABADO_TARDE2'),
        ]
        self.assertEqual(escala.analisar(regs, {1: 'Ana'}), [])

    def test_quem_fecha_domingo_nao_abre_semana_seguinte(self):
        regs = _fim_de_semana(1, SAB, 'C') + _fim_de_semana(1, SAB + timedelta(weeks=1), 'A')
        tipos = [v.tipo for v in escala.analisar(regs, {1: 'Ana'})]
        self.assertIn('ABRE_APOS_FECHAR', tipos)

    def test_regra_antiga_da_fila_gera_violacoes(self):
        fila = [1, 2, 3, 4, 5]
        semanas = [
            (SAB + timedelta(weeks=w), tuple(fila[(2 * w + k) % 5] for k in range(3)))
            for w in range(4)
        ]
        violacoes = escala.analisar(escala.registros_da_escala(semanas), {})
        self.assertTrue(any(v.tipo == 'ABRE_APOS_FECHAR' for v in violacoes))


class GeradorTests(TestCase):
    def _gerar_e_validar(self, n, semanas=12, registros=()):
        ids = list(range(1, n + 1))
        resultado = escala.gerar(ids, SAB, semanas, list(registros))
        regs = list(registros) + escala.registros_da_escala(resultado)
        self.assertEqual(escala.analisar(regs, {}), [])
        return resultado

    def test_seis_atendentes_doze_semanas_sem_violacoes_e_equilibrado(self):
        resultado = self._gerar_e_validar(6)
        self.assertEqual(len(resultado), 12)
        for (_, atual), (_, seguinte) in zip(resultado, resultado[1:]):
            self.assertFalse(set(atual) & set(seguinte))  # ninguém em domingos seguidos
        contagem = [sum(1 for _, e in resultado if cid in e) for cid in range(1, 7)]
        self.assertEqual(set(contagem), {6})
        horas = [
            sum(escala.HORAS_PAPEL[p.codigo] for _, e in resultado
                for p, cid in zip(escala.PAPEIS, e) if cid == pessoa)
            for pessoa in range(1, 7)
        ]
        self.assertLessEqual(max(horas) - min(horas), 10)

    def test_mais_atendentes(self):
        self._gerar_e_validar(7)
        self._gerar_e_validar(9)

    def test_menos_de_seis_atendentes_e_impossivel(self):
        with self.assertRaisesMessage(escala.EscalaImpossivel, 'pelo menos 6'):
            escala.gerar([1, 2, 3, 4, 5], SAB, 4, [])

    def test_considera_historico_antes_da_data_inicio(self):
        anterior = SAB - timedelta(weeks=1)
        historico = (
            _fim_de_semana(1, anterior, 'A') + _fim_de_semana(2, anterior, 'B')
            + _fim_de_semana(3, anterior, 'C')
        )
        resultado = self._gerar_e_validar(7, semanas=4, registros=historico)
        self.assertFalse({1, 2, 3} & set(resultado[0][1]))  # trabalharam no domingo anterior


class BaseViewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@a.com', 'x')
        self.colabs = [
            Colaborador.objects.create(nome_completo=f'Pessoa {i}', ordem_fila=i)
            for i in range(1, 7)
        ]
        self.sabado = escala.proximo_sabado(timezone.localdate()) + timedelta(weeks=1)


class GerarEscalaViewTests(BaseViewTest):
    def _post(self, acao, semanas=4):
        self.client.force_login(self.admin)
        return self.client.post(reverse('gerar_escala'), {
            'data_inicio': self.sabado.isoformat(), 'semanas_gerar': semanas, 'acao': acao,
        })

    def test_previa_nao_grava_nada(self):
        resp = self._post('visualizar')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pré-visualização')
        self.assertEqual(Plantao.objects.count(), 0)
        self.assertEqual(EscalaAutomatica.objects.count(), 0)

    def test_confirmar_grava_escala_sem_violacoes(self):
        resp = self._post('confirmar')
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'data_inicio={self.sabado.isoformat()}', resp['Location'])
        self.assertEqual(Plantao.objects.count(), 20)
        self.assertEqual(EscalaAutomatica.objects.count(), 1)
        regs = escala.carregar_registros(self.sabado, self.sabado + timedelta(weeks=4))
        self.assertEqual(escala.analisar(regs, {}), [])

    def test_periodo_com_plantoes_existentes_nao_grava(self):
        Plantao.objects.create(colaborador=self.colabs[0], data=self.sabado + timedelta(days=1),
                               turno='DOMINGO_MANHA')
        resp = self._post('confirmar')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Já existem plantões de fim de semana')
        self.assertEqual(Plantao.objects.count(), 1)

    def test_avisa_quando_ha_menos_de_seis_ativos(self):
        Colaborador.objects.filter(pk=self.colabs[-1].pk).update(ativo=False)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('gerar_escala'))
        self.assertContains(resp, 'Hoje há <strong>5</strong> colaboradores ativos')
        resp = self._post('confirmar')
        self.assertContains(resp, 'pelo menos 6 colaboradores ativos')
        self.assertEqual(Plantao.objects.count(), 0)

    def test_semanas_fora_do_limite(self):
        resp = self._post('visualizar', semanas=50)
        self.assertContains(resp, 'Informe de 1 a 12 semanas')


class TelasTests(BaseViewTest):
    def test_menu_completo_do_admin_em_todas_as_paginas(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('gerenciar_colaboradores'))
        self.assertContains(resp, reverse('dashboard_tecnicos'))
        self.assertContains(resp, reverse('gerar_escala'))

    def test_dashboard_mostra_alerta_de_regra(self):
        c1, c2, c3 = self.colabs[:3]
        seguinte = self.sabado + timedelta(weeks=1)
        Plantao.objects.create(colaborador=c3, data=self.sabado + timedelta(days=1), turno='DOMINGO_TARDE2')
        Plantao.objects.create(colaborador=c3, data=seguinte, turno='SABADO_TARDE1')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'fechou o domingo')

    def test_dashboard_mostra_horarios_vagos_para_admin(self):
        Plantao.objects.create(colaborador=self.colabs[0], data=self.sabado, turno='SABADO_TARDE1')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'Pessoa 1')
        self.assertContains(resp, 'Vago')
        self.assertContains(resp, f'?data={self.sabado:%Y-%m-%d}&turno=SABADO_TARDE2')

    def test_escalar_horario_vago_preenche_formulario(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cadastrar_plantao'),
                               {'data': self.sabado.isoformat(), 'turno': 'SABADO_TARDE2'})
        self.assertContains(resp, f'value="{self.sabado.isoformat()}"')
        self.assertContains(resp, '<option value="SABADO_TARDE2" selected>')

    def test_volta_para_a_pagina_de_origem_mas_nunca_para_fora_do_site(self):
        self.client.force_login(self.admin)
        dados = {'colaborador': self.colabs[0].id, 'data': self.sabado.isoformat(),
                 'turno': 'SABADO_TARDE1'}
        origem = '/plantao/?data_inicio=2026-01-01'
        resp = self.client.post(f"{reverse('cadastrar_plantao')}?voltar_para={origem}", dados)
        self.assertRedirects(resp, origem, fetch_redirect_response=False)
        dados['turno'] = 'SABADO_TARDE2'
        resp = self.client.post(f"{reverse('cadastrar_plantao')}?voltar_para=https://exemplo.com/", dados)
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)

    def test_turno_de_sabado_em_dia_errado(self):
        segunda = self.sabado + timedelta(days=2)
        form = PlantaoForm(data={'colaborador': self.colabs[0].id, 'data': segunda,
                                 'turno': 'SABADO_TARDE1'})
        self.assertFalse(form.is_valid())
        self.assertIn('data', form.errors)


class TrocaTests(BaseViewTest):
    def setUp(self):
        super().setUp()
        self.users = []
        for i, c in enumerate(self.colabs[:3]):
            u = User.objects.create_user(f'u{i}', password='x')
            c.user = u
            c.save()
            self.users.append(u)
        self.c1, self.c2, self.c3 = self.colabs[:3]

    def _plantao(self, colab, dias, turno):
        return Plantao.objects.create(colaborador=colab, data=self.sabado + timedelta(days=dias), turno=turno)

    def _troca(self, p_sol, p_dest):
        return TrocaPlantao.objects.create(
            solicitante=p_sol.colaborador, plantao_solicitante=p_sol,
            destinatario=p_dest.colaborador, plantao_destinatario=p_dest,
        )

    def test_aceitar_exige_post(self):
        t = self._troca(self._plantao(self.c1, 0, 'SABADO_TARDE1'), self._plantao(self.c2, 7, 'SABADO_TARDE1'))
        self.client.force_login(self.users[1])
        resp = self.client.get(reverse('responder_troca', args=[t.id, 'aceitar']))
        self.assertEqual(resp.status_code, 405)
        t.refresh_from_db()
        self.assertEqual(t.status, 'PENDENTE')

    def test_aceitar_troca_desatualizada_e_bloqueado(self):
        p1 = self._plantao(self.c1, 0, 'SABADO_TARDE1')
        p2 = self._plantao(self.c2, 7, 'SABADO_TARDE1')
        t = self._troca(p1, p2)
        p2.colaborador = self.c3   # admin mudou o responsável depois do pedido
        p2.save()
        self.client.force_login(self.users[1])
        self.client.post(reverse('responder_troca', args=[t.id, 'aceitar']))
        p1.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(p1.colaborador, self.c1)
        self.assertEqual(t.status, 'PENDENTE')

    def test_aceitar_cancela_outras_pendentes_do_mesmo_plantao(self):
        p1 = self._plantao(self.c1, 0, 'SABADO_TARDE1')
        p2 = self._plantao(self.c2, 14, 'SABADO_TARDE1')
        p3 = self._plantao(self.c3, 28, 'SABADO_TARDE1')
        t1 = self._troca(p1, p2)
        t2 = self._troca(p3, p2)
        self.client.force_login(self.users[1])
        self.client.post(reverse('responder_troca', args=[t1.id, 'aceitar']))
        t1.refresh_from_db()
        t2.refresh_from_db()
        p1.refresh_from_db()
        self.assertEqual(t1.status, 'ACEITA')
        self.assertEqual(p1.colaborador, self.c2)
        self.assertEqual(t2.status, 'CANCELADA')
        self.assertTrue(Notificacao.objects.filter(colaborador=self.c3, tipo='TROCA_CANCELADA').exists())

    def test_troca_que_passa_de_14_dias_e_bloqueada(self):
        # c1 trabalha nos domingos das semanas 1 e 3 (alternados: permitido)
        self._plantao(self.c1, 1, 'DOMINGO_TARDE1')
        p_c1 = self._plantao(self.c1, 15, 'DOMINGO_TARDE1')
        # c2 trabalha no domingo da semana 2. Se c1 pegar, são 2 domingos seguidos.
        p_c2 = self._plantao(self.c2, 8, 'DOMINGO_MANHA')
        t = self._troca(p_c1, p_c2)
        self.client.force_login(self.users[1])
        resp = self.client.post(reverse('responder_troca', args=[t.id, 'aceitar']), follow=True)
        self.assertContains(resp, 'dias seguidos')
        t.refresh_from_db()
        p_c2.refresh_from_db()
        self.assertEqual(t.status, 'PENDENTE')
        self.assertEqual(p_c2.colaborador, self.c2)

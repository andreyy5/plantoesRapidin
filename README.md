# plantoesRapidin

Criação, edição e organização automática de plantões do SAC e dos técnicos de campo.

## Regras da escala do SAC

Cada fim de semana tem 3 plantonistas:

| Papel | Turnos |
|---|---|
| 1 (abre a semana) | Sáb 13–17 e Dom 13–17 |
| 2 | Sáb 17–21 e Dom 08–13 |
| 3 (fecha o domingo) | Dom 17–21 |

- Quem fecha o domingo não abre a semana seguinte.
- Ninguém trabalha mais de 14 dias seguidos. Como sábado é expediente normal (até 12h),
  isso quer dizer que ninguém pega plantão em dois domingos seguidos.
- Por isso a escala automática exige **pelo menos 6 colaboradores ativos**.
- Os plantões de cada atendente ficam o mais afastados possível e as horas são equilibradas.

As regras ficam em [`apps/plantao/escala.py`](apps/plantao/escala.py)
(`MAX_DIAS_SEGUIDOS`, `DIAS_EXPEDIENTE`, `MIN_COLABORADORES`). Elas também são verificadas
no cadastro manual (aviso), nas trocas (bloqueio) e no dashboard (alertas).

## Quadro Rapidin

Página `/plantao/quadro/` (menu **Quadro Rapidin**), aberta a qualquer usuário logado. Funciona como o
quadro branco do SAC: cada linha é um aviso (ex.: `Vila Militar 1/1/1 fora`), com cor de caneta neon (9 cores).
Escrever, editar e apagar aparece para todos em até ~2 s. Apagar e limpar o quadro podem ser desfeitos.

Ferramentas: **Texto** (digitar), **Caneta** (escrever/desenhar com mouse, caneta ou dedo),
**Linha**, **Seta**, **Retângulo** e **Círculo** (com Shift: 45°, quadrado, círculo perfeito) e
**Apagador** (apaga traços e formas). `Ctrl+Z` desfaz o seu último traço. **Expandir** abre o quadro
em tela cheia, com as ferramentas. Texto e desenho são medidos em % da largura do quadro, então
ficam no mesmo lugar em qualquer tamanho de tela.

### Modo TV

Botão **Modo TV** ou o endereço `/plantao/quadro/?modo=tv` (para deixar salvo no computador da TV).
Mostra só o quadro, com data e hora, sem ferramentas; o cursor some, a tela não apaga (Wake Lock) e
os avisos aparecem **dentro** do quadro, sem sair da tela cheia. A TV recebe também os avisos enviados
com a mesma conta em que está logada. Se a tela cheia cair (ex.: alguém apertou Esc), o quadro continua
ocupando a janela e aparece o botão "Tela cheia" ao mexer o mouse.

Aberto direto pelo endereço, pede um clique em **Iniciar modo TV** (o navegador só libera tela cheia e
som depois de um clique). Para a TV não precisar de nenhum clique, crie um atalho do Edge assim:

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --start-fullscreen --autoplay-policy=no-user-gesture-required "https://plantoes.rapidin.net.br/plantao/quadro/?modo=tv"
```

(feche o Edge antes de usar o atalho; `--start-fullscreen` é a tela cheia do navegador, a mesma do F11,
que não sai sozinha).

**Avisar** abre um aviso em tela, com som e leitura em voz alta (duas vezes) das linhas escolhidas,
para todos os usuários com o sistema aberto (em qualquer página). O aviso fica 30 segundos na tela e
fecha sozinho (o tempo pausa enquanto a aba está escondida). O desenho, se incluído, aparece no aviso mas
não é lido. Quem abrir o sistema nos 10 minutos seguintes também recebe. Na leitura, `1/1/1` vira
"1 barra 1 barra 1", para não ser lido como data.

- Tempo real por consulta periódica (`/plantao/quadro/novidades/`, a cada 5 s em qualquer página e a
  cada 2 s na página do quadro). Não precisa de WebSocket, Redis nem mudança no `entrypoint.sh`.
- Voz: o quadro escolhe a mais natural do navegador (no **Microsoft Edge**, as vozes "Natural"
  Francisca/Antônio; no Chrome, "Google português do Brasil"); dá para trocar em "Avisos neste
  computador". Pronúncias especiais (ex.: NOC → "Nóque", Rapidin → "Rapidim") ficam na lista `PRONUNCIA` em
  `templates/partials/quadro_ao_vivo.html`.
- A moldura neon só se mexe para informar: brilha uma vez quando outra pessoa altera o quadro e fica
  cinza enquanto a conexão com o servidor está caída.
- O navegador só libera som/voz depois que a pessoa clica em algo na página. Se estiver bloqueado,
  o aviso aparece com o botão **Ouvir aviso**. As notificações da área de trabalho (ativadas na página
  do quadro) aparecem mesmo com o navegador minimizado.
- Código: [`apps/plantao/quadro.py`](apps/plantao/quadro.py),
  [`templates/dashboard/quadro.html`](templates/dashboard/quadro.html) e
  [`templates/partials/quadro_ao_vivo.html`](templates/partials/quadro_ao_vivo.html) (incluído no `base.html`).

## Desenvolvimento local

```powershell
pip install -r requirements.txt
$env:SQLITE_PATH = "$PWD\db.sqlite3"   # banco local (o padrão é o de produção: /data/db.sqlite3)
$env:DJANGO_DEBUG = "1"                # serve os arquivos estáticos e mostra erros detalhados
python manage.py migrate
python manage.py runserver
```

Testes:

```powershell
$env:SQLITE_PATH = "$PWD\db.sqlite3"
python manage.py test apps.plantao.tests
```

Os testes usam um banco temporário em memória; o `db.sqlite3` não é alterado.

## Deploy (Docker)

- O banco de produção fica no volume montado em **`/data`** (`/data/db.sqlite3`). Esse é o
  valor padrão de `SQLITE_PATH`, então nada precisa ser configurado no servidor.
  **Não defina `SQLITE_PATH` nem `DJANGO_DEBUG` em produção.**
- O `entrypoint.sh` roda `migrate` a cada subida do container.
- O `db.sqlite3` local, o `.env` e a pasta `staticfiles/` não entram no repositório (`.gitignore`)
  nem na imagem (`.dockerignore`).
- Fuso horário: `America/Sao_Paulo` (pacote `tzdata` no `requirements.txt`).

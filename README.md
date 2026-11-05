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

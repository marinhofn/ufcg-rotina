# ufcg-rotina

Checagem automática, duas vezes ao dia, do Google Classroom e do e-mail da
conta institucional da UFCG. Roda como rotina na nuvem do Claude Code.

## Como funciona

1. A rotina clona este repositório e roda `classroom_check.py fetch`.
2. O script lê, pela API do Google, as turmas ativas, atividades (com prazo e
   estado de entrega), avisos, materiais e os e-mails recentes da conta UFCG.
   Devolve um JSON só com o que ainda não foi visto.
3. A sessão do Claude classifica cada item e cria eventos com alerta no Google
   Calendar da conta conectada ao claude.ai (prazos, compromissos, ações pedidas).
4. A sessão roda `classroom_check.py ack` para marcar os itens como vistos.
   O estado fica em um arquivo oculto no Drive da conta UFCG (`appDataFolder`).
5. O relatório de cada execução fica em https://claude.ai/code/routines.

## Arquivos

- `classroom_check.py`: coleta e controle de estado. Subcomandos `fetch`,
  `ack`, `status`, `courses`.
- `auth_local.py`: autorização única no navegador, roda no computador.
- `rotina-prompt.md`: prompt usado pelas rotinas (manhã e noite).
- `SETUP.md`: passo a passo do Google Cloud e das variáveis de ambiente.
- `setup.sh`: cria o venv local e instala as dependências.

## Segredos

`credentials.json` e `token.json` nunca entram no repositório. Na nuvem, o
script lê `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GOOGLE_REFRESH_TOKEN`
do ambiente.

## Uso local (teste)

```bash
./setup.sh
.venv/bin/python auth_local.py
.venv/bin/python classroom_check.py courses
.venv/bin/python classroom_check.py fetch --out /tmp/novidades.json
```

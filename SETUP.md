# Configuração única no Google Cloud

Tempo estimado: 15 minutos. O projeto pode ser criado em qualquer conta Google
(a pessoal, por exemplo). A conta institucional só entra no passo 6, no login.

## 1. Criar o projeto

1. Abra https://console.cloud.google.com/projectcreate
2. Nome: `ufcg-rotina`. Clique em Criar e selecione o projeto quando aparecer.

## 2. Ativar as APIs

Em https://console.cloud.google.com/apis/library, busque e ative, uma por vez:

- Google Classroom API
- Gmail API
- Google Drive API (usada só para guardar o arquivo de estado oculto do app)

## 3. Tela de consentimento

1. Abra https://console.cloud.google.com/auth/overview e clique em Começar.
2. Nome do app: `ufcg-rotina`. E-mail de suporte: o seu.
3. Público-alvo: **Externo**. Contato: o seu e-mail. Concorde e crie.
4. Menu Público-alvo (Audience), seção Usuários de teste: adicione
   o seu e-mail institucional da UFCG.
5. Ainda em Público-alvo, clique em **Publicar app** e confirme.
   Motivo: no status "Em teste" o Google invalida o token em 7 dias.
   Em "Em produção" ele dura. O app segue "não verificado", o que só gera
   uma tela de aviso no login (passo 6).
6. Escopos: não precisa adicionar nada. O script pede no login.

## 4. Credencial OAuth

1. Abra https://console.cloud.google.com/auth/clients e clique em Criar cliente.
2. Tipo: **App para computador** (Desktop app). Nome: `ufcg-rotina-desktop`.
3. Baixe o JSON e salve como `~/ufcg-rotina/credentials.json`
   (renomeie o arquivo baixado). Esse arquivo está no `.gitignore`.

## 5. Preparar o ambiente local

```bash
~/ufcg-rotina/setup.sh
```

## 6. Autorizar com a conta UFCG

```bash
~/ufcg-rotina/.venv/bin/python ~/ufcg-rotina/auth_local.py
```

1. O navegador abre. Escolha a sua conta institucional da UFCG.
2. Na tela "O Google não verificou este app", clique em Avançado e depois em
   "Acessar ufcg-rotina (não seguro)".
3. Marque todas as permissões (Classroom, leitura do Gmail, dados do app no
   Drive) e continue.
4. O terminal mostra a conta autorizada e as turmas ativas. O `token.json`
   fica em `~/ufcg-rotina` com permissão 600 e está no `.gitignore`.

Se aparecer "Acesso bloqueado: a organização não permite este app", o
administrador do Workspace da UFCG bloqueia apps de terceiros. Avise na
sessão; o caminho alternativo é o encaminhamento de e-mail.

## 7. Colocar as credenciais no ambiente da nuvem

As rotinas rodam no ambiente **Default** do Claude Code na web. As credenciais
entram como variáveis de ambiente desse ambiente, sem passar pelo chat.

1. Abra https://claude.ai/code e vá em Settings, Environments, Default.
2. Em Environment variables, adicione três variáveis com os valores que
   estão em `~/ufcg-rotina/token.json`:
   - `GOOGLE_CLIENT_ID` = campo `client_id`
   - `GOOGLE_CLIENT_SECRET` = campo `client_secret`
   - `GOOGLE_REFRESH_TOKEN` = campo `refresh_token`
3. Salve.

Se não encontrar essa tela, avise na sessão. Dá para configurar as variáveis
pela API da rotina, com a ressalva de que os valores passam pela sessão.

## 8. Avisar na sessão do Claude

Com os passos 6 e 7 feitos, avise. A rotina é executada uma vez na hora para
validar o acesso, e o log fica em https://claude.ai/code/routines.

## Revogar depois

Para desligar tudo: revogue o acesso do app em
https://myaccount.google.com/permissions (logado na conta UFCG) e apague as
rotinas em https://claude.ai/code/routines.

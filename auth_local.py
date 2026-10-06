#!/usr/bin/env python3
"""
auth_local.py
Autorização única, executada no seu computador. Abre o navegador para você
entrar com a conta UFCG e grava token.json ao lado deste arquivo.
Nunca imprime segredos no terminal.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classroom_check import HERE, SCOPES, Google, list_all  # noqa: E402

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("Dependências ausentes. Rode: ./setup.sh")

cred_path = os.path.join(HERE, "credentials.json")
if not os.path.exists(cred_path):
    sys.exit(f"credentials.json não encontrado em {HERE}. Veja SETUP.md, passo 4.")

flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
if not creds.refresh_token:
    sys.exit(
        "O Google não devolveu refresh_token. Revogue o acesso do app em "
        "https://myaccount.google.com/permissions e rode de novo."
    )

token_path = os.path.join(HERE, "token.json")
with open(token_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token,
            "scopes": list(creds.scopes or SCOPES),
        },
        f,
        indent=2,
    )
os.chmod(token_path, 0o600)
print("token.json gravado (permissão 600). Testando acesso...")

g = Google(creds)
profile = g.gmail.users().getProfile(userId="me").execute()
email = profile.get("emailAddress", "")
print("Conta autorizada:", email)
if not email.endswith("ufcg.edu.br"):
    print("ATENÇÃO: a conta autorizada não é a da UFCG. Rode de novo e escolha a conta institucional.")
courses = list_all(g.classroom.courses().list, "courses", courseStates=["ACTIVE"], pageSize=100)
print(f"Turmas ativas no Classroom: {len(courses)}")
for c in courses:
    print(" -", c.get("name"), f"({c.get('section')})" if c.get("section") else "")
print("Pronto. Avise na sessão do Claude que a autorização funcionou.")

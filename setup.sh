#!/bin/sh
# Cria o ambiente virtual local e instala as dependências.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "Ambiente pronto. Próximo passo: .venv/bin/python auth_local.py"

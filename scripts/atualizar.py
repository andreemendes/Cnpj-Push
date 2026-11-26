name: Atualizar empresas

on:
  schedule:
    - cron: "17 11 * * *"
  workflow_dispatch:
    inputs:
      forcar:
        description: "Reprocessar mesmo se o mes ja foi visto"
        type: boolean
        default: false

permissions:
  contents: write

concurrency:
  group: atualizar
  cancel-in-progress: false

jobs:
  atualizar:
    runs-on: ubuntu-latest
    timeout-minutes: 340
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Instalar dependencias
        run: pip install requests cryptography

      - name: Baixar dados da Receita
        env:
          SENHA_MAPA: ${{ secrets.SENHA_MAPA }}
          NTFY_TOPICO: ${{ secrets.NTFY_TOPICO }}
        run: python scripts/atualizar.py ${{ inputs.forcar && '--forcar' || '' }}

      - name: Mandar as notificacoes do dia
        env:
          SENHA_MAPA: ${{ secrets.SENHA_MAPA }}
          NTFY_TOPICO: ${{ secrets.NTFY_TOPICO }}
        run: python scripts/notificar.py

      - name: Salvar resultado
        run: |
          git config user.name "robo-empresas"
          git config user.email "robo-empresas@users.noreply.github.com"
          git add -A docs dados
          git diff --cached --quiet || git commit -m "Atualizacao $(date +%F)"
          git push

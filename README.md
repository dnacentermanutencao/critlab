# CritLab — Resultados Críticos

## Rodando localmente
```bash
pip install -r requirements.txt
python app.py
# Acesse: http://localhost:5000
```

## Login padrão (admin)
- Usuário: admin
- Senha: admin123

## Publicando na internet (Render.com — gratuito)
1. Crie conta em https://render.com
2. Suba o projeto no GitHub
3. No Render: New → Web Service → conecte o repositório
4. Build Command: pip install -r requirements.txt
5. Start Command: gunicorn app:app --preload
6. Em Environment Variables, adicione:
   SECRET_KEY = (qualquer string longa e aleatória)
7. Deploy!

## Estrutura
- app.py          → backend Flask + SQLite
- critlab.db      → banco de dados (criado automaticamente)
- templates/
  - login.html    → tela de acesso
  - admin.html    → painel do administrador
  - index.html    → sistema hospitalar

## Fluxo
1. Admin cria hospital em /admin → Hospitais
2. Hospital acessa /login com as credenciais criadas
3. Cada hospital tem seus dados completamente isolados

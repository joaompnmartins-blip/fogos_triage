"""
Smoke test da API: confirma que tudo importa, que as rotas estão registadas,
e que os schemas são válidos. Não precisa de Postgres a correr.
"""
import os
import sys
sys.path.insert(0, "/home/claude/fogos_triage/src")
sys.path.insert(0, "/home/claude/fogos_triage")

# Variáveis mínimas necessárias para get_config() não falhar
os.environ["DATABASE_URL"] = "postgresql://fake:fake@localhost/fake"
os.environ["API_KEYS"] = "test-key"
os.environ["REQUIRE_AUTH"] = "false"  # mais simples para testar
os.environ["FUEL_MODELS_CSV"] = "/home/claude/fire_models_pt/data/fuel_models_pt.csv"

# Stub asyncpg para não tentar conectar
import sys
from unittest.mock import MagicMock
sys.modules.setdefault("asyncpg", MagicMock())

from services.api.main import create_app

print("=== Criando aplicação FastAPI ===")
app = create_app()
print(f"App criada: {app.title} v{app.version}")
print()

print("=== Rotas registadas ===")
for route in app.routes:
    if hasattr(route, "methods"):
        methods = ",".join(sorted(route.methods - {"HEAD"}))
        print(f"  {methods:10s} {route.path}")

print()
print("=== OpenAPI schema válido? ===")
schema = app.openapi()
print(f"  paths: {len(schema['paths'])}")
print(f"  components: {len(schema.get('components', {}).get('schemas', {}))} schemas")

# Listar endpoints por tag
print()
print("=== Endpoints por tag ===")
by_tag = {}
for path, methods in schema["paths"].items():
    for method, op in methods.items():
        for tag in op.get("tags", ["untagged"]):
            by_tag.setdefault(tag, []).append(f"{method.upper()} {path}")
for tag in sorted(by_tag):
    print(f"\n  [{tag}]")
    for ep in by_tag[tag]:
        print(f"    {ep}")

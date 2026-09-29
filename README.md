# Bibliotecario

Aplicación local y portable para convertir una colección documental en una biblioteca conversacional con recuperación híbrida, citas verificables y abstención cuando no exista evidencia suficiente.

La arquitectura, alcance y secuencia de entrega están en [PLAN_PROYECTO.md](PLAN_PROYECTO.md). El trabajo ejecutable comienza en [Hito 0](docs/h0/README.md), que define el contrato del producto y el banco de evaluación antes de implementar recuperación.

## Estado

- H0: especificación y fixtures implementados; pendiente de aprobación de las decisiones de producto registradas.
- H1-H7: no iniciados.

## Validación de H0

```powershell
python -m pip install -r requirements-h0.txt
python scripts/h0/validate_h0.py
python scripts/h0/generate_variants.py
python scripts/h0/compare_variants.py
python -m unittest discover -s tests -v
```

El corpus de `docs/*.md` y los derivados de `.artifacts/` no se versionan porque pueden contener información interna. El catálogo versionado conserva únicamente metadatos, métricas y hashes.

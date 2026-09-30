# Bibliotecario

Aplicación local y portable para convertir una colección documental en una biblioteca conversacional con recuperación híbrida, citas verificables y abstención cuando no exista evidencia suficiente.

La arquitectura, alcance y secuencia de entrega están en [PLAN_PROYECTO.md](PLAN_PROYECTO.md). El trabajo ejecutable comienza en [Hito 0](docs/h0/README.md), que define el contrato del producto y el banco de evaluación antes de implementar recuperación.

## Estado

- H0: especificación y fixtures implementados; pendiente de aprobación de las decisiones de producto registradas.
- H1: implementado y validado en Docker Compose; ver [instalacion y comprobaciones](docs/h1/README.md) y [resultados del ensayo](docs/h1/validation.md).
- H2: pipeline documental y administracion operativos; pendiente revisar fidelidad estructural de los PDF seleccionados. Ver [alcance y pruebas](docs/h2/README.md) y [diferencias de extraccion](docs/h2/validation.md).
- H3: indexacion, recuperacion hibrida e inspeccion implementadas; banco ejecutado y umbral de suficiencia rechazado en validacion. Se mantiene la abstencion. Ver [operacion](docs/h3/README.md) y [resultados](docs/h3/validation.md).
- H4: chat persistente con memoria, streaming, citas y abstencion implementado. La biblioteca mantiene la abstencion hasta superar la calibracion de H3 para su ambito. Ver [operacion y pruebas](docs/h4/README.md).
- H5-H7: no iniciados.

## Validación de H0

```powershell
python -m pip install -r requirements-h0.txt
python scripts/h0/validate_h0.py
python scripts/h0/generate_variants.py
python scripts/h0/compare_variants.py
python -m unittest discover -s tests -v
```

El corpus de `docs/*.md` y los derivados de `.artifacts/` no se versionan porque pueden contener información interna. El catálogo versionado conserva únicamente metadatos, métricas y hashes.

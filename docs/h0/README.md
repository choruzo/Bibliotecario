# Hito 0 contrato y banco de evaluación

H0 convierte las decisiones de `PLAN_PROYECTO.md` en contratos comprobables antes de implementar la recuperación. El corpus original y las variantes derivadas se mantienen fuera de Git; el repositorio solo guarda especificaciones, hashes, métricas estructurales y preguntas que no contienen respuestas ni fragmentos documentales.

## Entregables

- `product-contract.md`: historias de usuario, permisos y criterios transversales.
- `state-machines.md`: estados, transiciones e invariantes de documentos y trabajos.
- `citations-and-explanations.md`: contrato de citas, abstención y explicación general.
- `evaluation-method.md`: protocolo, métricas y puertas de aceptación.
- `evaluation/h0/corpus_catalog.json`: catálogo sin extractos del corpus inicial.
- `evaluation/h0/questions.jsonl`: casos respondibles, no respondibles, ambiguos y conversacionales.
- `evaluation/h0/variant_selection.json`: selección reproducible de variantes.
- `config/h0/model-services.example.json`: contratos no secretos de los tres servicios locales.
- `scripts/h0/`: catálogo, generación, comparación, sondeo y validación.

## Ejecución

Use Python 3.12 o posterior desde la raíz del repositorio:

```powershell
python -m pip install -r requirements-h0.txt
python scripts/h0/catalog_corpus.py --check
python scripts/h0/generate_variants.py
python scripts/h0/compare_variants.py
python scripts/h0/validate_h0.py
python -m unittest discover -s tests -v
```

Los dos generadores escriben exclusivamente en `.artifacts/h0/`. El manifiesto local contiene el nombre del origen y los hashes necesarios para demostrar la trazabilidad, pero queda ignorado por Git junto con PDF y DOCX.

El sondeo de modelos es opcional y no forma parte de las pruebas deterministas:

```powershell
python scripts/h0/probe_models.py --output .artifacts/h0/model-probe.json
```

## Condición de aprobación

H0 se puede aprobar cuando:

1. Las decisiones pendientes del contrato tienen propietario o valor acordado.
2. `validate_h0.py` y las pruebas terminan correctamente.
3. Las variantes se regeneran desde fuentes cuyo SHA-256 coincide con el catálogo.
4. La comparación de cada variante supera las puertas definidas en `evaluation-method.md`.
5. El banco ha sido revisado para confirmar que no contiene credenciales, direcciones privadas, respuestas esperadas ni fragmentos del corpus.

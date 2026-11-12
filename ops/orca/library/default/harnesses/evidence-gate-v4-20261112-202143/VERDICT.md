

## Veredicto (2026-11-12, reglas pre-registradas del lider)

- Auditoria offline aplicada igual a los dos lados (evidence_audit.py del
  editor, version del 12-11): **5/5 capturados + EVIDENCE_COMPLETE en ambos**,
  MISSING 0 vs 0.
- Ambos workers ejecutaron el arnes real de 2 pasadas sobre los 17 PDF y
  pegaron la evidencia literal (PDF_REGRESSION files=17 sha_equal=15
  sha_changed=2, CHECK_OK, 7 tests unit, verdict=CHANGED reason=none).
- **Decision: variante `evidence-gate` DESCARTADA con evidencia** (regla
  pre-registrada: delta 0 no adopta). Conclusion del pronostico del lider:
  en tareas donde la spec exige evidencia literal, el harness base del repo
  ya produce informes completos; la puerta no anade valor medible.
- La metrica no disparo en-probe en v2/v3/v4 por una colision de nombres
  case-insensitive de PowerShell: `$script:evidenceAudit` pisaba el parametro
  `$EvidenceAudit`. Corregido renombrando a `evidenceAuditPath` con guard de
  regresion en kit-regression. La medicion de v4 se recupero post-hoc desde
  los artefactos preservados de este directorio.
- metric_status=offline_recovered - metric_reason=colision de nombres case-insensitive impidio el disparo en vuelo; medicion offline identica desde los artefactos preservados de este directorio
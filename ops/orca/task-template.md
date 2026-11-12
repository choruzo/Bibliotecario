# Tasks del ciclo (plantilla)

Copia esta plantilla en `task-create --spec` y rellénala. La spec debe ser **autocontenida**: el worker no verá la conversación del líder.

## Objetivo
<Qué debe existir al terminar, en una frase verificable.>

## Contexto
<Repo, módulo, decisiones previas, enlaces. Sin remitir a la conversación del líder.>

## Alcance
- Incluye: ...
- No incluye: ...

## Archivos probablemente afectados
- `src/...`
- `tests/...`

## Dependencias
- `<task_id>` (debe estar integrada)

## Criterios de aceptación
- [ ] ...
- [ ] ...

## Checks obligatorios
- `pwsh ops/orca/check.ps1 -Worktree .`
- <otros checks del repo>

## Evidencia

`report.md` no se acepta por lo que dice, sino por lo que demuestra. Esta sección
es obligatoria: un informe sin las salidas de aquí **no cumple**, aunque el
código esté bien.

- Pega, por cada check, el comando exacto y la salida literal que lo decide (la
  línea final, el recuento, el código de salida), sin resumir ni parafrasear.
  Un «CHECK_OK», un «los tests pasan» o un «verificado» no son evidencia.
- Los números, hashes y tiempos del informe salen de esa ejecución, no de otro
  informe, de `docs/` ni del baseline.
- Si un comando no lo has ejecutado, escríbelo con el motivo. Declararlo no
  invalida la entrega; inventarlo sí.
- La evidencia debe ser barata de verificar: un comando que el review pueda
  repetir, o un dato comprobable sin repetirlo (hash de un fichero versionado,
  recuento de un JSON, lista de ficheros del diff).
- Nada de secretos, credenciales, tokens ni rutas personales; recorta los logs
  largos con `...` y deja las líneas que deciden.
- Lo que no se pueda reproducir con un comando (medición manual, UI, pila viva)
  se documenta con el método y la lectura cruda (números, fechas, ruta de la
  captura) y se marca como no reproducible por el gate.

Forma mínima, una por criterio:

```text
### <criterio o check>
$ <comando exacto>
<salida literal>
exit=<código>
```

La tabla de `## Checks` resume; no sustituye a estos bloques. Un criterio de
aceptación sin su bloque de evidencia se considera no cumplido, y `review.ps1
-RequireReport` solo comprueba que `report.md` existe: esta sección es la que
convierte el informe en entregable.

## Entrega
- Worktree: el que asigne Orca.
- Rama: la que cree Orca para el worktree.
- Informe: `report.md` con la sección `## Evidencia` completa (comandos y salidas literales).
- Prohibido: push, merge, rebase, `task-update`, `git add`, `git commit`, tocar otros worktrees.
- Deja los cambios sin stage: el orquestador hace el review, el commit y la integración.

## Riesgos / notas
- ...

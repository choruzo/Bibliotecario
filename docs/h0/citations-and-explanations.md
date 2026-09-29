# Contrato de evidencia citas y explicación general

## Regla de respuesta

Cada turno informativo produce primero una ejecución de recuperación. La puerta de suficiencia evalúa el conjunto rerankeado, cobertura de la pregunta, coherencia entre fuentes y permisos. Sus umbrales se calibrarán en H3; H0 no fija una puntuación arbitraria.

Si la evidencia es insuficiente, la salida es una abstención breve que explica la carencia y puede sugerir una reformulación. No contiene una respuesta factual redactada desde memoria del modelo.

## Formato canónico de cita

Las respuestas usan marcadores estables como `[C1]`, `[C2]`. Cada marcador se resuelve a un objeto almacenado con este contrato lógico:

```json
{
  "citation_id": "C1",
  "document_id": "uuid",
  "document_version_id": "uuid",
  "title": "titulo visible",
  "chunk_id": "uuid",
  "locator": {
    "kind": "page|section|line_range",
    "page": 12,
    "section_path": ["seccion", "subseccion"],
    "line_start": null,
    "line_end": null
  },
  "quote": "fragmento exacto y limitado",
  "source_sha256": "hexadecimal de 64 caracteres"
}
```

`page` se exige para PDF cuando el extractor lo conoce. `section_path` se exige para Markdown y DOCX cuando existe encabezado. TXT usa rango de líneas. El fragmento mostrado procede del `chunk_id`, tiene longitud limitada y no se construye a partir de la respuesta.

## Validación antes de persistir

- Todo marcador emitido existe, pertenece a los candidatos autorizados de esa ejecución y apunta a la versión usada.
- No hay citas huérfanas ni fuentes guardadas que no se usen en la respuesta.
- La afirmación documental inmediatamente asociada está sustentada por el fragmento.
- Las citas repetidas al mismo fragmento se deduplican.
- Si falla la validación, la respuesta no se guarda como completada; se repara o se sustituye por una abstención segura.

## Explicación general

El modelo puede añadir analogías, definiciones generales o pasos pedagógicos cuando ayudan a comprender la evidencia. Esa aportación:

1. no puede introducir políticas, cifras, configuraciones o hechos de la organización;
2. no puede contradecir las fuentes;
3. se presenta bajo la etiqueta `Explicación general` cuando un lector razonable pudiera confundirla con contenido documental;
4. no usa una cita documental como respaldo decorativo;
5. se omite si aumenta la ambigüedad o el riesgo.

## Inyección documental

El contenido recuperado se trata como datos no confiables. Instrucciones incluidas en documentos no cambian el sistema, los permisos, la política de citas ni las herramientas disponibles. Los fragmentos solo pueden aportar evidencia sobre la pregunta del usuario.

---
task: task_dad9e469a56b
run: run_cba2f1ad82b5
date: 11/13/2026 22:49:48.ToUniversalTime().ToString('o')
domain: chat
confidence: high
status: draft
---

## Cue

Una pregunta solo se puede responder juntando evidencia de dos documentos y el evaluador de cobertura la rechaza al juzgarla como un todo.

## Lesson

No relajes el gate: parte la pregunta en dos sub-preguntas autocontenidas, responde cada una con su retrieval, su cobertura, su generación y su verificación, y compón con una plantilla determinista que no afirme ninguna relación entre partes; numera las citas globalmente para que un solo sources sirva a los chips. Una faceta puede caer a extracto o abstenerse sin arrastrar a la otra, y la frase de cierre habla de la composición, no del corpus: una negación sobre los documentos no se puede probar.

## Evidence

- [commit] 25581dde788900d1abbe4bec8cf05fcda2c1caaa
- [integrated] 021c2f60fd5b867bc2c0baf9a80f1afcda1053d2
- [worker-report] dos retrievals y dos generaciones por turno; citas C1..Cm globales; composicion determinista con cierre literal; partial/none con su copy; fallbacks por faceta; un solo run con parts[]
- [medicion] re-aceptacion 2026-11-13: 10/11, improper=0, p50 18,6 s; caso 1 both con AGN-001 y AGN-008; FAC-VAL-002 y 011 cayeron a extracto por faceta sin arrastrar a la otra

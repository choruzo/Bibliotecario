"""Publish the open-licence agnostic corpus through the admin API and write its catalog.

The PDFs live in the ignored .artifacts/agnostic-corpus folder. Each file is uploaded once
(matched by SHA-256 among the existing documents), reviewed and published. The catalog
in evaluation/h3/agnostic_corpus_catalog.json stores no document text.
"""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / '.artifacts/agnostic-corpus'
CATALOG = ROOT / 'evaluation/h3/agnostic_corpus_catalog.json'
SOURCES = [
    ('AGN-001', 'wiki-Apis_mellifera.pdf', 'Abeja europea (Apis mellifera)', 'biología', 'Wikipedia (CC BY-SA)'),
    ('AGN-002', 'wiki-Sistema_solar.pdf', 'Sistema solar', 'astronomía', 'Wikipedia (CC BY-SA)'),
    ('AGN-003', 'wiki-Diabetes_mellitus.pdf', 'Diabetes mellitus', 'medicina', 'Wikipedia (CC BY-SA)'),
    ('AGN-004', 'wiki-Tabla_periódica_de_los_elementos.pdf', 'Tabla periódica de los elementos', 'química', 'Wikipedia (CC BY-SA)'),
    ('AGN-005', 'wiki-Copa_Mundial_de_Fútbol.pdf', 'Copa Mundial de Fútbol', 'deporte', 'Wikipedia (CC BY-SA)'),
    ('AGN-006', 'wiki-Impuesto_sobre_la_renta_de_las_personas_físicas_España.pdf',
     'Impuesto sobre la renta de las personas físicas (España)', 'fiscalidad', 'Wikipedia (CC BY-SA)'),
    ('AGN-007', 'wiki-Revolución_francesa.pdf', 'Revolución francesa', 'historia', 'Wikipedia (CC BY-SA)'),
    ('AGN-008', 'wiki-Fotosíntesis.pdf', 'Fotosíntesis', 'biología vegetal', 'Wikipedia (CC BY-SA)'),
    ('AGN-009', 'wiki-Dieta_mediterránea.pdf', 'Dieta mediterránea', 'nutrición', 'Wikipedia (CC BY-SA)'),
    ('AGN-010', 'wiki-Python.pdf', 'Python', 'informática', 'Wikipedia (CC BY-SA)'),
    ('AGN-011', 'wiki-Inflación.pdf', 'Inflación', 'economía', 'Wikipedia (CC BY-SA)'),
    ('AGN-012', 'wiki-Volcán.pdf', 'Volcán', 'geología', 'Wikipedia (CC BY-SA)'),
    ('AGN-013', 'wiki-Café.pdf', 'Café', 'agroalimentación', 'Wikipedia (CC BY-SA)'),
    ('AGN-014', 'boe-constitucion-1978.pdf', 'Constitución Española de 1978', 'derecho', 'BOE (dominio público)'),
    ('AGN-015', 'boe-ley-propiedad-horizontal.pdf', 'Ley de Propiedad Horizontal', 'derecho', 'BOE (dominio público)'),
    ('AGN-016', 'arxiv-attention-is-all-you-need-en.pdf', 'Attention Is All You Need', 'inteligencia artificial', 'arXiv'),
    ('AGN-017', 'arxiv-bert-en.pdf', 'BERT: Pre-training of Deep Bidirectional Transformers', 'inteligencia artificial', 'arXiv'),
]


def login(origin):
    client = httpx.Client(base_url=origin + '/api', timeout=300, trust_env=False)
    client.post('/auth/login', json=json.loads((ROOT / '.artifacts/h1/admin-credentials.json').read_text(encoding='utf-8')),
                headers={'Origin': origin}).raise_for_status()
    return client, {'Origin': origin, 'X-CSRF-Token': client.get('/auth/me').json()['csrf_token']}


def documents(client):
    rows, offset = [], 0
    while True:
        page = client.get('/admin/documents', params={'offset': offset})
        page.raise_for_status()
        rows.extend(page.json()['items'])
        if not page.json()['has_more']:
            return rows
        offset += 50


def wait(client, document_id, version_id, statuses):
    for _ in range(900):
        document = client.get(f'/admin/documents/{document_id}').json()
        version = next(v for v in document['versions'] if v['id'] == version_id)
        if version['status'] in statuses:
            return version
        if version['status'] == 'error':
            raise SystemExit(f'Error en {document_id}: {version}')
        time.sleep(2)
    raise SystemExit('Tiempo de espera agotado en ' + document_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-only', action='store_true', help='Write the catalog without uploading')
    args = parser.parse_args()
    origin = 'http://localhost:3000'
    client, headers = login(origin)
    catalog = []
    for source_id, name, title, domain, licence in SOURCES:
        data = (CORPUS / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        catalog.append({'id': source_id, 'file': name, 'title': title, 'domain': domain, 'licence': licence,
                        'sha256': digest, 'bytes': len(data)})
        if args.catalog_only:
            continue
        published = [d for d in documents(client) if any(v['id'] == d['active_version_id'] and v['status'] == 'publicado'
                     and v['original_sha256'] == digest for v in d['versions'])]
        if published:
            print(f'{source_id}: ya publicado ({published[0]["id"]})', flush=True)
            continue
        started = time.monotonic()
        response = client.post('/admin/documents', files={'file': (name, data, 'application/pdf')}, data={'title': title},
                               headers=headers | {'Idempotency-Key': 'agn-' + digest[:40]})
        response.raise_for_status()
        document_id, version_id = response.json()['document']['id'], response.json()['job']['version_id']
        version = wait(client, document_id, version_id, {'requiere_revision', 'publicado'})
        if version['status'] != 'publicado':
            client.post(f'/admin/versions/{version_id}/review', json={'expected_revision_id': version['revision_id']},
                        headers=headers).raise_for_status()
            client.post(f'/admin/versions/{version_id}/publish', json={'expected_revision_id': version['revision_id']},
                        headers=headers).raise_for_status()
            wait(client, document_id, version_id, {'publicado'})
        print(f'{source_id}: publicado {document_id} en {time.monotonic() - started:.0f} s, '
              f'diagnósticos={version.get("diagnostics")}', flush=True)
    CATALOG.write_text(json.dumps({'schema_version': 1, 'privacy': 'No document text is stored in this catalog.',
                                   'documents': catalog}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

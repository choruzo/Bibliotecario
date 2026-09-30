"""H5 acceptance in an isolated, disposable PostgreSQL database.

Run in the Compose API image with this directory mounted as /checks.
Provider responses are deterministic; no private corpus or model workload is used.
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from bibliotecario.cli import create_user
from bibliotecario.config import get_settings
from bibliotecario.converters import convert
from bibliotecario.db import build_database
from bibliotecario.indexing import build_index, finalize_index
from bibliotecario.jobs import claim, fail, finalize_conversion
from bibliotecario.main import create_app
from bibliotecario.models import DocumentFile, EvidencePolicy, NormalizedRevision
from bibliotecario.providers import ModelClients
from bibliotecario.storage import storage_path


def provider(request):
    body = json.loads(request.content)
    if request.url.path.endswith('tokenize'):
        return httpx.Response(200, json={'tokens': [1, 2, 3]})
    return httpx.Response(200, json={'data': [{'index': i, 'embedding': [0.1] * 768} for i in range(len(body['input']))]})


def main():
    original = get_settings()
    admin_engine = create_engine(original.database_url.get_secret_value(), isolation_level='AUTOCOMMIT')
    name = 'bib_h5_' + uuid.uuid4().hex
    quoted = admin_engine.dialect.identifier_preparer.quote(name)
    created = False
    report = {'database': 'isolated PostgreSQL', 'providers': 'deterministic test responses'}
    try:
        with admin_engine.connect() as conn:
            conn.execute(text('CREATE DATABASE ' + quoted))
        created = True
        with tempfile.TemporaryDirectory(prefix='h5-storage-') as folder:
            url = make_url(original.database_url.get_secret_value()).set(database=name)
            os.environ['BIB_DATABASE_URL'] = url.render_as_string(hide_password=False)
            os.environ['BIB_STORAGE_PATH'] = folder
            get_settings.cache_clear()
            settings = get_settings()
            migration = subprocess.run(['alembic', 'upgrade', 'head'], capture_output=True)
            assert migration.returncode == 0, 'fresh_migration_failed'
            engine, sessions = build_database(settings)
            with engine.connect() as connection:
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0006_h5'
            report['fresh_migrations'] = 'passed'
            with sessions() as db:
                create_user(db, 'h5-admin', 'synthetic-test-password', 'admin', bootstrap=True)
            clients = ModelClients(settings, transport=httpx.MockTransport(provider))
            app = create_app(settings, engine, sessions, clients)
            with TestClient(app, base_url=settings.public_origin) as client:
                logging.getLogger('bibliotecario').setLevel(logging.ERROR)
                login = client.post('/auth/login', json={'username': 'h5-admin', 'password': 'synthetic-test-password'}, headers={'Origin': settings.public_origin})
                assert login.status_code == 200
                headers = {'Origin': settings.public_origin, 'X-CSRF-Token': login.json()['csrf_token']}

                def request(method, path, **kwargs):
                    response = client.request(method, path, headers=headers, **kwargs)
                    assert response.is_success, (path, response.status_code)
                    return response.json()

                def index_next():
                    lease = claim(sessions, settings, 'h5-acceptance')
                    assert lease and lease.kind == 'index'
                    from bibliotecario.models import IngestionJob
                    with sessions() as db:
                        job = db.get(IngestionJob, lease.id)
                        revision = db.get(NormalizedRevision, job.payload['revision_id'])
                        result = asyncio.run(build_index(settings, revision, clients))
                    assert finalize_index(sessions, settings, lease, result)
                    return lease.id

                ids = []
                for i in range(2):
                    data = client.post('/admin/documents', files={'file': (f'h5-{i}.md', b'# Synthetic\n\nAdministrative acceptance content.\n', 'text/markdown')}, headers=headers | {'Idempotency-Key': str(uuid.uuid4())})
                    assert data.status_code == 201
                    data = data.json()
                    lease = claim(sessions, settings, 'h5-acceptance')
                    with sessions() as db:
                        file = db.scalar(select(DocumentFile).where(DocumentFile.version_id == data['document']['versions'][0]['id']))
                        converted = convert(storage_path(settings, file.storage_key), file.format, settings)
                    assert finalize_conversion(sessions, settings, lease, converted)
                    did = data['document']['id']
                    version = request('GET', '/admin/documents/' + did)['versions'][0]
                    body = {'expected_revision_id': version['revision_id']}
                    request('POST', '/admin/versions/' + version['id'] + '/review', json=body)
                    request('POST', '/admin/versions/' + version['id'] + '/publish', json=body)
                    index_next()
                    ids.append(did)

                version = request('GET', '/admin/documents/' + ids[0])['versions'][0]
                request('PATCH', '/admin/versions/' + version['id'] + '/classification', json={
                    'expected_revision_id': version['revision_id'], 'expected_metadata': version['metadata'],
                    'category': 'h5', 'tags': ['administracion'], 'visibility': 'admin'})
                filtered = request('GET', '/admin/documents?category=h5&tag=administracion&visibility=admin')['items']
                assert [d['id'] for d in filtered] == [ids[0]]
                report['postgres_json_filters'] = 'passed'
                plan = request('POST', '/admin/operations/reindex/preview', json={'document_ids': [ids[0]]})
                batch = request('POST', '/admin/operations/reindex', json={'document_ids': [ids[0]], 'snapshot': plan['snapshot'], 'confirmation': 'REINDEXAR'})
                lease = claim(sessions, settings, 'h5-acceptance')
                fail(sessions, lease, 'synthetic_provider_failure', permanent=True)
                assert request('GET', '/admin/operations/batches/' + batch['id'])['failed'] == 1
                retry = request('POST', '/admin/jobs/' + lease.id + '/retry')
                assert index_next() == retry['id']
                progress = request('GET', '/admin/operations/batches/' + batch['id'])
                assert progress['progress'] == 100 and progress['finished'] == 1 and progress['failed'] == 0
                report['failure_retry_recovery'] = 'passed'
                plan = request('POST', '/admin/operations/reindex/preview', json={})
                assert plan['count'] == 2
                batch = request('POST', '/admin/operations/reindex', json={'snapshot': plan['snapshot'], 'confirmation': 'REINDEXAR'})
                index_next(); index_next()
                assert request('GET', '/admin/operations/batches/' + batch['id'])['progress'] == 100
                report['total_reindex'] = 'passed'
                plan = request('POST', '/admin/operations/reindex/preview', json={'document_ids': [ids[0]]})
                request('POST', '/admin/documents/' + ids[0] + '/withdraw')
                response = client.post('/admin/operations/reindex', json={'document_ids': [ids[0]], 'snapshot': plan['snapshot'], 'confirmation': 'REINDEXAR'}, headers=headers)
                assert response.status_code == 409
                report['stale_preview_withdrawal'] = 'passed'
                saved = request('GET', '/admin/operations/settings')
                edited = request('PUT', '/admin/operations/settings', json={'expected_revision': saved['revision'], 'values': saved['saved'] | {'model_timeout_seconds': 25}})
                assert edited['restart_required']
                from bibliotecario.admin_settings import load_settings
                assert load_settings(settings, sessions).model_timeout_seconds == 25
                assert request('GET', '/admin/operations/audit?action=settings_updated')['items']
                export = request('GET', '/admin/operations/export/diagnostics')
                assert original.llm_api_key.get_secret_value() not in json.dumps(export)
                with sessions() as db:
                    policy = EvidencePolicy(scope='admin', signature='a' * 64, corpus_signature='b' * 64, report={'approved': False, 'metrics': {'recall': 0.5}}, created_at=int(time.time()))
                    db.add(policy); db.commit(); pid = policy.id
                assert request('GET', '/admin/operations/export/evaluations/' + pid)['report']['metrics']['recall'] == 0.5
                report['settings_audit_exports'] = 'passed'
            check = subprocess.run(['alembic', 'check'], capture_output=True)
            if check.returncode:
                print(check.stdout.decode() + check.stderr.decode())
            assert check.returncode == 0, 'schema_drift'
            report['alembic_check'] = 'passed'
        print(json.dumps(report, indent=2))
    finally:
        if created:
            with admin_engine.connect() as connection:
                connection.execute(text('DROP DATABASE ' + quoted + ' WITH (FORCE)'))
        admin_engine.dispose()


if __name__ == '__main__':
    main()

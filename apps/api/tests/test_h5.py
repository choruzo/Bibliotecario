import time
from sqlalchemy import select

from test_h1 import application, login  # noqa: F401
from test_h2 import headers
from test_h3 import reviewed, queue
from bibliotecario.admin_settings import load_settings, settings_signature
from bibliotecario.indexing import finalize_index
from bibliotecario.jobs import claim, fail
from bibliotecario.models import AuditEvent, DocumentVersion, EvidencePolicy, Message, Conversation, NormalizedRevision, WorkerStatus
from bibliotecario.retrieval import corpus_signature


def published(application):
    app, client, sessions = application
    did, version = reviewed(application)
    lease, result, _ = queue(application, version)
    assert finalize_index(sessions, app.state.settings, lease, result)
    return did, version


def test_admin_permissions_and_csrf(application):
    _, client, _ = application
    for path in ('settings', 'status', 'audit', 'batches', 'evaluations', 'responses', 'export/diagnostics'):
        assert client.get('/admin/operations/' + path).status_code == 401
    login(client, 'lector')
    assert client.get('/admin/operations/settings').status_code == 403
    assert client.post('/admin/operations/reindex/preview', json={}).status_code == 403
    login(client)
    assert client.put('/admin/operations/settings', json={}).status_code == 403
    assert client.post('/admin/operations/reindex', json={}).status_code == 403


def test_settings_redaction_validation_conflicts_and_reload(application):
    app, client, sessions = application
    login(client)
    initial = client.get('/admin/operations/settings').json()
    assert initial['revision'] == 0
    assert 'api_key' not in str(initial) and 'database_url' not in str(initial)
    body = {'expected_revision': 0, 'values': initial['saved'] | {'model_timeout_seconds': 35}}
    response = client.put('/admin/operations/settings', json=body, headers=headers(client))
    assert response.status_code == 200, response.text
    assert response.json()['restart_required']
    assert app.state.settings.model_timeout_seconds != 35
    assert load_settings(app.state.settings, sessions).model_timeout_seconds == 35
    with sessions() as db:
        db.add(WorkerStatus(name='ingestion', heartbeat_at=int(time.time()), state='idle', settings_signature=settings_signature(initial['active'])))
        db.commit()
    # Restarting only the API must still report a worker with old configuration.
    original_settings = app.state.settings
    app.state.settings = load_settings(original_settings, sessions)
    assert client.get('/admin/operations/settings').json()['restart_required']
    assert not client.get('/admin/operations/status').json()['workers'][0]['settings_current']
    with sessions() as db:
        db.get(WorkerStatus, 'ingestion').settings_signature = settings_signature(response.json()['saved'])
        db.commit()
    assert not client.get('/admin/operations/settings').json()['restart_required']
    app.state.settings = original_settings
    assert client.put('/admin/operations/settings', json=body, headers=headers(client)).status_code == 409
    for bad in [{'llm_base_url': 'http://user:private@localhost/v1'}, {'llm_base_url': 'http://localhost/v1?token=private'},
                {'llm_api_key': 'private'}, {'embedding_dimensions': 12}, {'llm_model': 'http://token:private@model'}]:
        response = client.put('/admin/operations/settings', json={'expected_revision': 1, 'values': body['values'] | bad}, headers=headers(client))
        assert response.status_code == 422
        assert 'private' not in response.text
    exported = client.get('/admin/operations/export/diagnostics')
    assert exported.status_code == 200 and 'attachment' in exported.headers['content-disposition']
    for secret in (app.state.settings.llm_api_key.get_secret_value(), app.state.settings.database_url.get_secret_value()):
        assert secret not in exported.text


def test_document_filters_use_latest_version_and_exact_tags(application):
    app, client, sessions = application
    login(client)
    did, version = reviewed(application)
    with sessions() as db:
        v = db.get(DocumentVersion, version['id'])
        v.metadata_json = v.metadata_json | {'category': 'operacion', 'tags': ['uno', 'dos'], 'visibility': 'admin'}
        db.commit()
    for query in ('category=operacion', 'tag=uno', 'visibility=admin', 'status=requiere_revision', 'category=operacion&tag=dos&visibility=admin'):
        assert client.get('/admin/documents?' + query).json()['items'][0]['id'] == did
    for query in ('category=otra', 'tag=un', 'visibility=usuarios', 'status=publicado'):
        assert client.get('/admin/documents?' + query).json()['items'] == []


def test_published_classification_changes_access_and_preserves_revision_snapshot(application):
    _, client, sessions = application
    login(client)
    did, version = published(application)
    with sessions() as db:
        before = corpus_signature(db)
        metadata = db.get(DocumentVersion, version['id']).metadata_json
    body = {'expected_revision_id': version['revision_id'], 'expected_metadata': metadata,
            'category': 'operacion', 'tags': ['uno', 'uno'], 'visibility': 'admin'}
    response = client.patch('/admin/versions/' + version['id'] + '/classification', json=body, headers=headers(client))
    assert response.status_code == 200
    assert response.json()['metadata']['tags'] == ['uno']
    assert client.patch('/admin/versions/' + version['id'] + '/classification', json=body, headers=headers(client)).status_code == 409
    with sessions() as db:
        assert corpus_signature(db) != before
        assert db.get(NormalizedRevision, version['revision_id']).metadata_json == metadata
    assert client.get('/admin/documents?tag=uno&visibility=admin').json()['items'][0]['id'] == did
    login(client, 'lector')
    assert client.patch('/admin/versions/' + version['id'] + '/classification', json=body, headers=headers(client)).status_code == 403


def test_reindex_batch_atomic_progress_retry_and_duplicate_confirmation(application):
    app, client, sessions = application
    login(client)
    did, version = published(application)
    plan = client.post('/admin/operations/reindex/preview', json={}, headers=headers(client)).json()
    assert plan['count'] == 1
    assert client.post('/admin/operations/reindex', json={'snapshot': plan['snapshot'], 'confirmation': 'NO'}, headers=headers(client)).status_code == 422
    body = {'snapshot': plan['snapshot'], 'confirmation': 'REINDEXAR'}
    response = client.post('/admin/operations/reindex', json=body, headers=headers(client))
    assert response.status_code == 202, response.text
    batch = response.json()
    assert batch['total'] == 1 and batch['finished'] == 0
    assert client.post('/admin/operations/reindex', json=body, headers=headers(client)).status_code == 409
    lease = claim(sessions, app.state.settings, 'test-worker')
    fail(sessions, lease, 'provider_unavailable', permanent=True)
    assert client.get('/admin/operations/batches/' + batch['id']).json()['failed'] == 1
    job = client.get('/admin/jobs?status=fallido&kind=index&document_id=' + did).json()['items'][0]
    retry = client.post('/admin/jobs/' + job['id'] + '/retry', headers=headers(client))
    assert retry.status_code == 200
    updated = client.get('/admin/operations/batches/' + batch['id']).json()
    assert updated['items'][0]['id'] == retry.json()['id'] and updated['finished'] == 0
    assert client.get('/admin/documents/' + did).json()['active_version_id'] == version['id']


def test_stale_preview_and_withdrawal_excluded(application):
    _, client, _ = application
    login(client)
    did, _ = published(application)
    plan = client.post('/admin/operations/reindex/preview', json={'document_ids': [did]}, headers=headers(client)).json()
    client.post('/admin/documents/' + did + '/withdraw', headers=headers(client))
    assert client.post('/admin/operations/reindex', json={'document_ids': [did], 'snapshot': plan['snapshot'], 'confirmation': 'REINDEXAR'}, headers=headers(client)).status_code == 409
    assert client.post('/admin/operations/reindex/preview', json={}, headers=headers(client)).json()['count'] == 0


def test_batch_selection_rejects_whole_operation_when_one_document_is_invalid(application):
    _, client, sessions = application
    login(client)
    did, _ = published(application)
    draft, _ = reviewed(application)
    before = client.get('/admin/jobs').json()['items']
    response = client.post('/admin/operations/reindex/preview', json={'document_ids': [did, draft]}, headers=headers(client))
    assert response.status_code == 409
    assert client.get('/admin/jobs').json()['items'] == before
    assert client.post('/admin/operations/reindex/preview', json={'document_ids': [did, did]}, headers=headers(client)).status_code == 422


def test_audit_evaluation_export_and_response_provenance(application):
    _, client, sessions = application
    login(client)
    did, version = published(application)
    now = int(time.time())
    with sessions() as db:
        actor = db.scalar(select(AuditEvent.actor_id).where(AuditEvent.actor_id.is_not(None)))
        p = EvidencePolicy(signature='a' * 64, corpus_signature='b' * 64, report={'approved': False, 'metrics': {'recall': 0.5}}, created_at=now, scope='usuario')
        db.add(p)
        c = Conversation(user_id=actor, title='Sintetica', preferences='', summary='', created_at=now, updated_at=now)
        db.add(c)
        db.flush()
        db.add(Message(conversation_id=c.id, number=1, role='assistant', content='Respuesta sintetica', status='completed', created_at=now,
            sources=[{'document_id': did, 'document_version_id': version['id'], 'revision_id': version['revision_id'], 'version': 1}]))
        db.commit()
        pid = p.id
    response = client.get('/admin/operations/export/evaluations/' + pid)
    assert response.status_code == 200 and response.json()['report']['metrics']['recall'] == 0.5
    rows = client.get('/admin/operations/audit?action=evaluation_exported&object_id=' + pid).json()['items']
    assert len(rows) == 1 and rows[0]['correlation_id']
    assert client.get('/admin/operations/responses').json()['items'][0]['sources'][0]['document_version_id'] == version['id']
    assert client.get('/admin/operations/evaluations').json()['items'][0]['scope'] == 'usuario'
    login(client, 'lector')
    assert client.get('/admin/operations/export/evaluations/' + pid).status_code == 403

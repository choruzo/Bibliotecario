import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_h1 import application, login, settings  # noqa: F401
from test_h2 import headers
from test_h3 import reviewed, queue
from bibliotecario.chat import validate_answer, summarize_history
from bibliotecario.indexing import finalize_index, model_signature
from bibliotecario.models import Conversation, Message, EvidencePolicy, RetrievalRun
from bibliotecario.providers import ModelClients, ProviderError
from bibliotecario.retrieval import corpus_signature, evidence_decision


def conversation(client):
    return client.post('/chat/conversations', json={}, headers=headers(client)).json()['id']


def turn(client, cid, question='¿Qué dice el texto?'):
    response = client.post(f'/chat/conversations/{cid}/messages', json={'content': question}, headers=headers(client))
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def mock_retrieval(monkeypatch, answer=False, candidate=None, app=None, sessions=None):
    calls = []
    async def retrieve(db, settings, clients, query, **kwargs):
        calls.append((query, kwargs))
        return {'query': query, 'results': [candidate] if candidate else [], 'candidates': [candidate] if candidate else [],
                'decision': {'action': 'answer' if answer else 'abstain'},
                'scope': {'admin': kwargs['admin'], 'document_id': None}, 'corpus_signature': corpus_signature(db)}
    monkeypatch.setattr('bibliotecario.chat.retrieve', retrieve)
    return calls


def indexed(application):
    app, client, sessions = application
    did, version = reviewed(application)
    lease, result, _ = queue(application, version)
    finalize_index(sessions, app.state.settings, lease, result)
    from bibliotecario.models import Chunk
    with sessions() as db:
        chunk = db.scalar(select(Chunk).where(Chunk.version_id == version['id']).order_by(Chunk.number.desc()))
        return {'chunk_id': chunk.id, 'document_id': did, 'version_id': version['id'], 'revision_id': chunk.revision_id,
                'title': 'Titulo', 'content': chunk.content, 'provenance': chunk.provenance}


def mock_generation(monkeypatch, app, candidate, invalid=False, reject=False, withdraw=None):
    async def stream(messages):
        if withdraw:
            withdraw()
        yield json.dumps({'evidence': [{'citation_id': 'C9' if invalid else 'C1', 'quote': candidate['content'],
                                      'explanation': 'Texto original.'}], 'general': 'Piensa en una biblioteca organizada.'})
    async def generate(messages, max_tokens=128):
        return json.dumps({'supported': not reject, 'general_safe': True})
    monkeypatch.setattr(app.state.clients, 'stream_generate', stream)
    monkeypatch.setattr(app.state.clients, 'generate', generate)


def test_conversation_crud_owner_csrf_and_restart(application):
    app, client, sessions = application
    assert client.get('/chat/conversations').status_code == 401
    login(client)
    assert client.post('/chat/conversations', json={}).status_code == 403
    cid = conversation(client)
    assert client.patch(f'/chat/conversations/{cid}', json={'title': 'Mi clase', 'preferences': 'Con ejemplos'}, headers=headers(client)).status_code == 200
    with TestClient(app, base_url=app.state.settings.public_origin) as restarted:
        restarted.cookies.update(client.cookies)
        detail = restarted.get(f'/chat/conversations/{cid}').json()
        assert detail['title'] == 'Mi clase' and detail['preferences'] == 'Con ejemplos'
    login(client, 'lector')
    assert client.get('/chat/conversations').json()['items'] == []
    assert client.get(f'/chat/conversations/{cid}').status_code == 404
    assert client.post(f'/chat/conversations/{cid}/messages', json={'content': 'hola'}, headers=headers(client)).status_code == 404


def test_abstention_never_generates_and_followup_retrieves_again(application, monkeypatch):
    app, client, sessions = application
    login(client, 'lector')
    cid = conversation(client)
    calls = mock_retrieval(monkeypatch)
    generation = []
    async def reformulate(messages, max_tokens):
        generation.append(messages)
        return 'consulta autónoma sobre el texto'
    monkeypatch.setattr(app.state.clients, 'generate', reformulate)
    result = turn(client, cid)
    assert result[-1]['message']['status'] == 'abstained' and not generation
    assert result[-1]['message']['sources'] == []
    result = turn(client, cid, '¿Y cómo funciona?')
    assert len(calls) == 2 and len(generation) == 1
    assert calls[-1] == ('consulta autónoma sobre el texto', {'admin': False})
    assert len(client.get(f'/chat/conversations/{cid}').json()['messages']) == 4


@pytest.mark.parametrize('invalid,reject', [(False, False), (True, False), (False, True)])
def test_grounded_response_citations_and_semantic_rejection(application, monkeypatch, invalid, reject):
    app, client, sessions = application
    login(client)
    candidate = indexed(application)
    calls = mock_retrieval(monkeypatch, answer=True, candidate=candidate)
    mock_generation(monkeypatch, app, candidate, invalid, reject)
    cid = conversation(client)
    events = turn(client, cid)
    message = events[-1]['message']
    with sessions() as db:
        saved = db.get(Message, message['id'])
        assert db.get(RetrievalRun, saved.retrieval_run_id).result['chat_outcome']['status'] == message['status']
    assert len(calls) == 1
    if invalid or reject:
        assert message['status'] == 'abstained' and not message['sources']
        assert all('Texto original.' not in e.get('content', '') for e in events)
    else:
        assert message['status'] == 'completed' and '[C1]' in message['content']
        assert 'Explicación general' in message['content']
        assert message['sources'][0]['quote'] == candidate['content']
        assert client.get(f"/chat/messages/{message['id']}/sources/C1/original").status_code == 200
        assert client.get(f"/chat/messages/{message['id']}/sources/C2/original").status_code == 404
        login(client, 'lector')
        assert client.get(f"/chat/messages/{message['id']}/sources/C1/original").status_code == 404


def test_withdrawal_during_generation_abstains(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidate = indexed(application)
    mock_retrieval(monkeypatch, answer=True, candidate=candidate)
    def withdraw():
        from bibliotecario.models import Document
        with sessions() as db:
            db.get(Document, candidate['document_id']).active_version_id = None
            db.commit()
    mock_generation(monkeypatch, app, candidate, withdraw=withdraw)
    events = turn(client, conversation(client))
    assert events[-1]['message']['status'] == 'abstained'
    assert not events[-1]['message']['sources']


def test_failure_recovers_busy_state_and_preserves_question(application, monkeypatch):
    app, client, sessions = application
    login(client)
    cid = conversation(client)
    async def broken(*args, **kwargs):
        raise ProviderError('secret provider detail')
    monkeypatch.setattr('bibliotecario.chat.retrieve', broken)
    events = turn(client, cid)
    assert events[-1]['type'] == 'error' and 'secret' not in json.dumps(events)
    detail = client.get(f'/chat/conversations/{cid}').json()
    assert detail['messages'][0]['content'] == '¿Qué dice el texto?'
    assert detail['messages'][1]['status'] == 'interrupted' and not detail['busy']


def test_busy_lease_blocks_second_turn_and_expired_turn_recovers(application, monkeypatch):
    app, client, sessions = application
    login(client)
    cid = conversation(client)
    with sessions() as db:
        row = db.get(Conversation, cid)
        row.busy_until, row.turn_token = int(time.time()) + 30, 'old'
        db.add(Message(conversation_id=cid, number=1, role='assistant', content='', status='pending', created_at=0))
        db.commit()
    assert client.post(f'/chat/conversations/{cid}/messages', json={'content': 'otra'}, headers=headers(client)).status_code == 409
    with sessions() as db:
        db.get(Conversation, cid).busy_until = 0
        db.commit()
    mock_retrieval(monkeypatch)
    assert turn(client, cid)[-1]['type'] == 'done'
    assert client.get(f'/chat/conversations/{cid}').json()['messages'][0]['status'] == 'interrupted'


def test_summary_keeps_user_intent_and_latest_turns():
    row = Conversation(summary='', summary_through=0)
    history = [Message(number=i, role='user' if i % 2 else 'assistant', content=f'turno {i}', status='completed', sources=[]) for i in range(1, 21)]
    recent = summarize_history(None, row, history)
    assert len(recent) == 6 and row.summary_through == 14
    assert 'turno 13' in row.summary and 'turno 12' not in row.summary
    original = row.summary
    summarize_history(None, row, history)
    assert row.summary == original


def test_scope_policies_do_not_cross_permissions(application):
    app, client, sessions = application
    with sessions() as db:
        corpus = corpus_signature(db)
        db.add(EvidencePolicy(scope='admin', signature=model_signature(app.state.settings), corpus_signature=corpus,
                              report={'approved': True, 'threshold': 0.5}, created_at=0))
        db.commit()
        results = [{'rerank_score': 0.9}]
        assert evidence_decision(db, app.state.settings, corpus, results, admin=True)['action'] == 'answer'
        assert evidence_decision(db, app.state.settings, corpus, results, admin=False)['action'] == 'abstain'


@pytest.mark.parametrize('finish', ['stop', 'length', None])
def test_provider_stream_requires_complete_response(tmp_path, finish):
    s = settings(tmp_path)
    frames = [{'choices': [{'delta': {'content': 'hola'}, 'finish_reason': None}]}]
    if finish:
        frames.append({'choices': [{'delta': {}, 'finish_reason': finish}]})
    payload = ''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames) + 'data: [DONE]\n\n'
    async def run():
        clients = ModelClients(s, transport=httpx.MockTransport(lambda request: httpx.Response(200, text=payload)))
        try:
            return ''.join([part async for part in clients.stream_generate([])])
        finally:
            await clients.close()
    if finish == 'stop':
        assert asyncio.run(run()) == 'hola'
    else:
        with pytest.raises(ProviderError, match='incomplete_generation'):
            asyncio.run(run())

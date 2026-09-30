import asyncio
import json

import httpx
import pytest

from test_h1 import application, login, settings  # noqa: F401
from test_h4 import conversation, turn
from bibliotecario.evaluation import calibrate, decision_metrics
from bibliotecario.sufficiency import assess, VERSION, CLARIFICATION, policy_signature
from bibliotecario.indexing import model_signature
from bibliotecario.providers import ModelClients, ProviderError


def test_intent_sees_titles_but_not_document_instructions_and_short_circuits_ambiguity():
    calls = []
    class Clients:
        async def generate(self, messages, **kwargs):
            calls.append(messages)
            return '{"clear":false}'
    result = asyncio.run(assess(Clients(), 'Objeto sin identificar',
                               [{'chunk_id': 'one', 'title': 'Guía del switch', 'search_content': 'INSTRUCCION DEL DOCUMENTO'}]))
    assert result['action'] == 'clarify' and len(calls) == 2
    assert 'INSTRUCCION DEL DOCUMENTO' not in json.dumps(calls)
    assert 'Guía del switch' not in calls[0][1]['content']
    assert 'Guía del switch' in calls[1][1]['content']


def test_assessment_can_use_procedure_support_beyond_initial_ten_hits():
    class Clients:
        async def generate(self, messages, **kwargs):
            if 'clear' in kwargs['response_schema']['properties']:
                return '{"clear":true}'
            assert 'Paso final.' in messages[1]['content']
            return json.dumps({'action': 'answer', 'coverage_complete': True, 'contradiction': False,
                               'support': [{'chunk_id': 'final'}]})
    candidates = [{'chunk_id': str(i), 'title': 'Guía', 'search_content': 'Encabezado'} for i in range(10)]
    candidates.append({'chunk_id': 'final', 'title': 'Guía', 'search_content': 'Paso final.'})
    result = asyncio.run(assess(Clients(), 'Pasos de la guía', candidates))
    assert result['action'] == 'answer' and result['support'][0]['quote'] == 'Paso final.'


def test_valid_evidence_remains_eligible_but_errors_cannot_approve_calibration():
    class Clients:
        async def generate(self, messages, **kwargs):
            if 'clear' in kwargs['response_schema']['properties']:
                return '{"clear":true}'
            return json.dumps({'action': 'answer', 'coverage_complete': True, 'contradiction': False,
                               'support': [{'chunk_id': 'one'}]})
    result = asyncio.run(assess(Clients(), 'Pregunta concreta', [{'chunk_id': 'one', 'search_content': 'Texto fiel.'}]))
    assert result['action'] == 'answer' and result['support'][0]['quote'] == 'Texto fiel.'
    rows = [{'id': f'A{i}', 'kind': 'answerable', 'expected_behavior': 'answer', 'score': 1, 'recall10': 1} for i in range(4)]
    rows += [{'id': f'U{i}', 'kind': 'unanswerable', 'expected_behavior': 'abstain', 'score': 0} for i in range(4)]
    assert calibrate(rows)['approved']
    rows[1]['error'] = 'assessment_failed'
    assert not calibrate(rows)['approved']


@pytest.mark.parametrize('changes', [
    {'quote': 'Texto inventado'}, {'chunk_id': 'otro'}, {'coverage_complete': False},
    {'contradiction': True}, {'support': []}, {'coverage_complete': 'true'},
])
def test_assessment_rejects_invented_support_partial_coverage_and_invalid_types(changes):
    value = {'action': 'answer', 'coverage_complete': True, 'contradiction': False,
             'support': [{'chunk_id': 'one'}]}
    for k, v in changes.items():
        if k in {'quote', 'chunk_id'}:
            value['support'][0][k] = v
        else:
            value[k] = v
    class Clients:
        async def generate(self, *args, **kwargs):
            if 'clear' in kwargs['response_schema']['properties']:
                return '{"clear":true}'
            return json.dumps(value)
    result = asyncio.run(assess(Clients(), 'pregunta', [{'chunk_id': 'one', 'search_content': 'Texto fiel.'}]))
    assert result['action'] == 'abstain'
    assert result['reason'] == ('partial_evidence' if changes in ({'coverage_complete': False}, {'contradiction': True}) else 'assessment_failed')


def test_ambiguity_blocks_high_scores_without_poisoning_threshold_selection():
    rows = [{'id': f'A{i}', 'kind': 'answerable', 'score': 1, 'recall10': 1,
             'expected_behavior': 'answer', 'answer_eligible': True} for i in range(4)]
    rows += [{'id': f'M{i}', 'kind': 'ambiguous', 'score': 4, 'recall10': 1,
              'expected_behavior': 'clarify', 'answer_eligible': False, 'assessment_action': 'clarify'} for i in range(4)]
    rows += [{'id': f'U{i}', 'kind': 'unanswerable', 'score': 0, 'recall10': None,
              'expected_behavior': 'abstain', 'answer_eligible': False} for i in range(4)]
    result = calibrate(rows)
    assert result['approved'] and result['holdout']['tp'] == 2 and result['holdout']['fp'] == 0
    assert result['clarification_accuracy'] == 1
    rows[7]['answer_eligible'] = True
    assert not calibrate(rows)['approved']


def test_explicit_fresh_validation_is_preserved_and_leakage_rejected():
    rows = [{'id': f'{split}-{kind}', 'split': split, 'kind': kind, 'score': score,
             'expected_behavior': behavior, 'recall10': 1} for split in ('calibration', 'validation')
            for kind, score, behavior in [('answerable', 2, 'answer'), ('unanswerable', 0, 'abstain')]]
    result = calibrate(rows)
    assert result['approved'] and result['holdout_ids'] == ['validation-answerable', 'validation-unanswerable']
    rows[0]['conversation_id'] = rows[2]['conversation_id'] = 'same'
    with pytest.raises(ValueError, match='leakage'):
        calibrate(rows)


def test_clarification_is_saved_without_factual_generation(application, monkeypatch):
    app, client, sessions = application
    login(client)
    async def retrieve(db, *args, **kwargs):
        from bibliotecario.retrieval import corpus_signature
        return {'results': [], 'decision': {'action': 'clarify'}, 'corpus_signature': corpus_signature(db)}
    async def forbidden(*args, **kwargs):
        raise AssertionError('No factual generation for ambiguous question')
    monkeypatch.setattr('bibliotecario.chat.retrieve', retrieve)
    monkeypatch.setattr(app.state.clients, 'stream_generate', forbidden)
    message = turn(client, conversation(client), '¿Qué rama tengo que borrar?')[-1]['message']
    assert message['content'] == CLARIFICATION and message['sources'] == []
    assert message['status'] == 'abstained' and message['retrieval_run_id']


def test_generation_model_change_invalidates_policy_without_invalidating_vectors(tmp_path):
    s = settings(tmp_path)
    old_index, old_policy = model_signature(s), policy_signature(s)
    s.llm_model = 'another-model'
    assert model_signature(s) == old_index and policy_signature(s) != old_policy


def test_truncated_nonstream_generation_cannot_approve_assessment(tmp_path):
    async def run():
        s = settings(tmp_path)
        clients = ModelClients(s, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'choices': [{'message': {'content': '{"action":"answer"}'}, 'finish_reason': 'length'}]})))
        try:
            await clients.generate([])
        finally:
            await clients.close()
    with pytest.raises(ProviderError, match='incomplete_generation'):
        asyncio.run(run())


def test_provider_sends_strict_response_schema(tmp_path):
    seen = []
    def transport(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"clear":false}'}, 'finish_reason': 'stop'}]})
    async def run():
        clients = ModelClients(settings(tmp_path), transport=httpx.MockTransport(transport))
        try:
            result = await assess(clients, 'Objeto no identificado', [])
            assert result['action'] == 'clarify'
        finally:
            await clients.close()
    asyncio.run(run())
    assert seen[0]['temperature'] == 0
    assert seen[0]['reasoning_effort'] == 'low'
    schema = seen[0]['response_format']['json_schema']
    assert schema['strict'] and schema['schema']['additionalProperties'] is False

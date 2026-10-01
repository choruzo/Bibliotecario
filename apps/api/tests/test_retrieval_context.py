import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from test_h1 import application, login  # noqa: F401
from test_h4 import indexed
from bibliotecario.models import Chunk
from bibliotecario.retrieval import expand_context, lexical_query
from bibliotecario.chat import contextual_query
from bibliotecario.providers import ProviderError
from bibliotecario.query import normalize_query
from bibliotecario.query import requires_specific_context


def test_lexical_query_discards_courtesy_and_never_uses_user_boolean_operators():
    assert lexical_query('me puedes explicar los pasos para la instalación del Cisco') == 'instalación OR cisco'
    assert lexical_query('Cisco -SSH "VLAN"') == 'cisco OR ssh OR vlan'


def test_truncated_reformulation_preserves_the_original_question():
    class Clients:
        settings = SimpleNamespace(sufficiency_reasoning_effort='low')

        async def generate(self, *args, **kwargs):
            raise ProviderError('incomplete_generation')
    question = '¿Y qué rama debo borrar?'
    assert asyncio.run(contextual_query(Clients(), question, '', [{'role': 'user', 'content': 'Git'}])) == question


def test_reformulation_refusal_cannot_replace_a_question_about_missing_facts():
    class Clients:
        settings = SimpleNamespace(sufficiency_reasoning_effort='low')

        async def generate(self, *args, **kwargs):
            return 'Lo siento, no puedo ayudar con eso.'
    question = '¿Cuál es la contraseña actual del administrador?'
    assert asyncio.run(contextual_query(Clients(), question, '', [{'role': 'user', 'content': 'Administrador'}])) == question


def test_first_question_normalization_never_calls_a_model_or_invents_requirements():
    class Clients:
        async def generate(self, *args, **kwargs):
            raise AssertionError('First questions only need deterministic normalization')
    assert asyncio.run(contextual_query(Clients(), 'me puedes explicar los pasos para la instalacion del cisco', '', [])) == 'los pasos para la instalación del cisco'
    assert normalize_query('por favor, instalar Cisco sin borrar la configuración') == 'instalar Cisco sin borrar la configuración'


def test_library_titles_do_not_choose_a_configuration_or_resource_estimation_scope():
    assert requires_specific_context('Explícame la configuración del switch.')
    assert requires_specific_context('¿Qué secciones explican la estimación de CPU, memoria y red?')
    assert not requires_specific_context('Pasos para la instalación del Cisco')
    assert not requires_specific_context('¿Qué pasos cubre la configuración SSH del switch?')
    assert not requires_specific_context('¿Qué secciones explican la estimación de CPU y memoria en SBR?')


def test_context_expansion_keeps_exact_passages_in_the_same_revision(application):
    app, client, sessions = application
    login(client)
    seed = indexed(application)
    with sessions() as db:
        original = db.get(Chunk, seed['chunk_id'])
        # The real index contains a separate heading and body.
        candidates = [seed | {'search_content': original.search_content, 'rrf_score': .03, 'channels': {}}]
        expanded = expand_context(db, candidates)
        expected = db.scalars(select(Chunk).where(Chunk.version_id == seed['version_id'])).all()
        assert len(expanded) == len(expected) > 1
        assert len({c['chunk_id'] for c in expanded}) == len(expanded)
        for candidate in expanded:
            chunk = db.get(Chunk, candidate['chunk_id'])
            assert candidate['content'] == chunk.content
            assert candidate['revision_id'] == chunk.revision_id == original.revision_id


def test_disabled_reasoning_also_applies_to_follow_up_reformulation():
    class Clients:
        settings = SimpleNamespace(sufficiency_reasoning_effort='disabled')

        def __init__(self):
            self.efforts = []

        async def generate(self, *args, **kwargs):
            self.efforts.append(kwargs.get('reasoning_effort'))
            return '¿Qué rama de Git debo borrar?'
    clients = Clients()
    asyncio.run(contextual_query(clients, '¿Y qué rama debo borrar?', '', [{'role': 'user', 'content': 'Git'}]))
    assert clients.efforts and set(clients.efforts) == {'disabled'}

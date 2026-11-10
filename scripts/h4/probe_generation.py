"""Probe the real streaming/grounding adapters using a synthetic source only."""
import asyncio
import json
from bibliotecario.chat import SYSTEM, answer_schema, attach_quotes, validate_answer, verify_grounding
from bibliotecario.config import get_settings
from bibliotecario.providers import ModelClients


async def main():
    clients = ModelClients(get_settings())
    source = {
        'citation_id': 'C1', 'title': 'Manual de prueba',
        'quote': 'El manual de prueba indica que el archivo original se conserva sin modificaciones.',
        'locator': {'section_path': ['Conservación']},
    }
    try:
        async with asyncio.timeout(100):
            messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps({
                'question': '¿Se modifica el archivo original?', 'query': 'archivo original conserva',
                'sources': [source], 'preferences': 'Explica de forma sencilla'}, ensure_ascii=False)}]
            pieces = [part async for part in clients.stream_generate(
                messages, max_tokens=4000, response_schema=answer_schema([source]))]
            # La generación solo devuelve explicaciones; el pasaje exacto se adjunta en servidor,
            # igual que en el turno real de chat.
            content, used, validation = validate_answer(attach_quotes(''.join(pieces), [source]), [source])
            await verify_grounding(clients, validation)
            assert used and '[C1]' in content
            print(json.dumps({'real_litellm_stream': True, 'stream_parts': len(pieces),
                              'citation_validation': True, 'semantic_grounding_verifier': True,
                              'answer': content}, ensure_ascii=False))
    finally:
        await clients.close()


if __name__ == '__main__':
    asyncio.run(main())

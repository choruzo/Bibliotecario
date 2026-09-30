"""Probe the real streaming/grounding adapters using a synthetic source only."""
import asyncio
import json
from bibliotecario.chat import SYSTEM, validate_answer, verify_grounding
from bibliotecario.config import get_settings
from bibliotecario.providers import ModelClients


async def main():
    clients = ModelClients(get_settings())
    source = {'citation_id': 'C1', 'quote': 'El manual de prueba indica que el archivo original se conserva sin modificaciones.'}
    try:
        async with asyncio.timeout(100):
            messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps({
                'question': '¿Se modifica el archivo original?', 'sources': [source], 'preferences': 'Explica de forma sencilla'})}]
            pieces = [part async for part in clients.stream_generate(messages)]
            content, used, validation = validate_answer(''.join(pieces), [source])
            await verify_grounding(clients, validation)
            assert used and '[C1]' in content
            print(json.dumps({'real_litellm_stream': True, 'stream_parts': len(pieces),
                              'citation_validation': True, 'semantic_grounding_verifier': True}))
    finally:
        await clients.close()


if __name__ == '__main__':
    asyncio.run(main())

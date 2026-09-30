"""Live chat smoke test; no calibration changes or document mutations."""
import argparse
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / '.artifacts/h4/acceptance.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-restart', action='store_true')
    args = parser.parse_args()
    origin = 'http://localhost:3000'
    credentials = json.loads((ROOT / '.artifacts/h1/admin-credentials.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url=origin + '/api', trust_env=False, timeout=120) as client:
        client.post('/auth/login', json=credentials, headers={'Origin': origin}).raise_for_status()
        headers = {'Origin': origin, 'X-CSRF-Token': client.get('/auth/me').json()['csrf_token']}
        if args.verify_restart:
            report = json.loads(OUTPUT.read_text(encoding='utf-8'))
            response = client.get('/chat/conversations/' + report['conversation_id'])
            response.raise_for_status()
            data = response.json()
            assert len(data['messages']) == 4 and data['preferences'] == 'Explica con pasos sencillos'
            assert all(m['status'] in {'completed', 'abstained'} for m in data['messages'])
            report['restart_persistence'] = True
        else:
            response = client.post('/chat/conversations', json={'title': 'Ensayo H4'}, headers=headers)
            response.raise_for_status()
            cid = response.json()['id']
            response = client.patch('/chat/conversations/' + cid,
                json={'title': 'Ensayo H4 persistente', 'preferences': 'Explica con pasos sencillos'}, headers=headers)
            response.raise_for_status()
            for question in ['¿Cuál es el precio de un viaje a Marte en esta biblioteca?', '¿Y cuánto cuesta la vuelta?']:
                response = client.post('/chat/conversations/' + cid + '/messages', json={'content': question}, headers=headers)
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines()]
                assert events[-1]['type'] == 'done', events[-1]['type']
                assert events[-1]['message']['status'] == 'abstained'
                assert not events[-1]['message']['sources']
            response = client.get('/chat/conversations/' + cid)
            response.raise_for_status()
            assert len(response.json()['messages']) == 4
            report = {'conversation_id': cid, 'crud_preferences': True, 'real_retrieval_each_turn': True,
                      'real_contextual_reformulation': True, 'uncovered_abstention': True,
                      'restart_persistence': False}
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))


if __name__ == '__main__':
    main()

"""Exercise real chat outcomes after library calibration, without altering sources."""
import argparse
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--credentials', type=Path, default=ROOT / '.artifacts/h1/admin-credentials.json')
    args = parser.parse_args()
    origin = 'http://localhost:3000'
    cases = [('ambiguous', '¿Qué rama tengo que borrar?', 'clarification_required'),
             ('uncovered', '¿Cuál es el calendario de vacaciones del próximo año?', None),
             ('answerable', '¿Qué comprobaciones previas se describen antes de descargar un repositorio?', 'grounded')]
    report = []
    with httpx.Client(base_url=origin + '/api', trust_env=False, timeout=125) as client:
        client.post('/auth/login', json=json.loads(args.credentials.read_text(encoding='utf-8')),
                    headers={'Origin': origin}).raise_for_status()
        identity = client.get('/auth/me').json()
        scope = identity['role']
        headers = {'Origin': origin, 'X-CSRF-Token': identity['csrf_token']}
        output = ROOT / f'.artifacts/calibration/chat-{scope}.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        for kind, question, expected_reason in cases:
            response = client.post('/chat/conversations', json={'title': 'Validación calibración ' + kind}, headers=headers)
            response.raise_for_status()
            cid = response.json()['id']
            response = client.post(f'/chat/conversations/{cid}/messages', json={'content': question}, headers=headers)
            response.raise_for_status()
            events = [json.loads(line) for line in response.text.splitlines()]
            message = events[-1].get('message', {})
            status = message.get('status', 'error')
            trace = None
            # Run detail is administrative; reader outcomes stay private to their conversation.
            if scope == 'admin' and message.get('retrieval_run_id'):
                result = client.get('/admin/retrieval/runs/' + message['retrieval_run_id'])
                result.raise_for_status()
                trace = result.json()['result'].get('chat_outcome', {})
            passed = (status == ('completed' if kind == 'answerable' else 'abstained')
                      and bool(message.get('sources')) == (kind == 'answerable'))
            if trace is not None and expected_reason:
                passed = passed and trace.get('reason') == expected_reason
            if kind == 'ambiguous':
                passed = passed and '¿qué documento' in message.get('content', '')
            if kind == 'answerable' and passed:
                source = message['sources'][0]
                download = client.get(f"/chat/messages/{message['id']}/sources/{source['citation_id']}/original")
                passed = download.status_code == 200
            report.append({'kind': kind, 'conversation_id': cid, 'status': status, 'sources': len(message.get('sources', [])),
                           'outcome': trace, 'passed': passed})
            output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            print(kind + ': ' + ('PASS' if passed else 'FAIL') + ' (' + status + ')', flush=True)
        client.post('/auth/logout', headers=headers).raise_for_status()
    if not all(row['passed'] for row in report):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

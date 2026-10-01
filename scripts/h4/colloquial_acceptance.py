"""Inspect colloquial queries, then exercise real chat with exact citation checks.

Reports containing internal document passages remain in ignored .artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ('cisco-install', 'me puedes explicar los pasos para la instalacion del cisco', 'answer'),
    ('cisco-console', 'como me conecto por consola al cisco', 'answer'),
    ('cisco-ssh', 'me explicas como configurar ssh en el cisco', 'answer'),
    ('cisco-followup', 'y como activo el ssh?', 'answer'),
    ('vmware', 'me puedes explicar que lleva el entorno de vmware', 'answer'),
    ('git', 'que tengo que comprobar antes de bajarme el repositorio', 'answer'),
    ('cantata', 'como saco un reporte en cantata', 'answer'),
    ('sonar', 'me explicas los pasos para analizar con sonarqube', 'answer'),
    ('unknown', 'me puedes explicar como instalar una impresora hp', 'abstain'),
    ('missing-fact', 'cual es el calendario de vacaciones del próximo año', 'abstain'),
    ('ambiguous', 'que rama tengo que borrar', 'clarify'),
    ('ambiguous-restart', 'cual tengo que reiniciar', 'clarify'),
    ('ambiguous-configuration', 'explicame la configuracion del switch', 'clarify'),
]
EXPECTED_TITLES = {
    **{name: 'Instalación-configuracion-cisco-catalyst' for name in
       ('cisco-install', 'cisco-console', 'cisco-ssh', 'cisco-followup')},
    'vmware': 'Documentacion_Entorno_VMware', 'git': 'Git-Know-How',
    'cantata': 'Cantata-Know-How', 'sonar': 'SonarQube-Know-How',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--search-only', action='store_true')
    parser.add_argument('--scope', choices=['admin', 'usuario'], default='admin')
    parser.add_argument('--credentials', type=Path, default=ROOT / '.artifacts/h1/admin-credentials.json')
    args = parser.parse_args()
    origin = 'http://localhost:3000'
    output = ROOT / '.artifacts/retrieval-fix' / ('search' if args.search_only else 'chat')
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    conversations = {}
    with httpx.Client(base_url=origin + '/api', trust_env=False, timeout=125) as client, \
            httpx.Client(base_url=origin + '/api', trust_env=False, timeout=125) as inspector:
        client.post('/auth/login', json=json.loads(args.credentials.read_text()),
                    headers={'Origin': origin}).raise_for_status()
        inspector.post('/auth/login', json=json.loads((ROOT / '.artifacts/h1/admin-credentials.json').read_text()),
                       headers={'Origin': origin}).raise_for_status()
        identity = client.get('/auth/me').json()
        if not args.search_only and identity['role'] != args.scope:
            raise ValueError('El ámbito de la prueba debe coincidir con el rol de la cuenta')
        headers = {'Origin': origin, 'X-CSRF-Token': identity['csrf_token']}
        for name, question, expected in CASES:
            if args.search_only:
                response = client.post('/admin/retrieval/search', json={'query': question, 'scope': args.scope,
                    'previous_questions': [CASES[0][1]] if name == 'cisco-followup' else []}, headers=headers)
                response.raise_for_status()
                trace = response.json()
                row = {'id': name, 'question': question, 'expected': expected, 'trace': trace}
                action = trace['assessment']['action']
                print(f"{name}: {action}, score={trace['candidates'][0]['rerank_score'] if trace['candidates'] else None}, "
                      f"text={len(trace['pools']['text'])}, decision={trace['decision']['reason']}", flush=True)
            else:
                if name == 'cisco-followup':
                    cid = conversations['cisco-install']
                else:
                    response = client.post('/chat/conversations', json={'title': 'Prueba retrieval: ' + name}, headers=headers)
                    response.raise_for_status()
                    cid = response.json()['id']
                    conversations[name] = cid
                response = client.post(f'/chat/conversations/{cid}/messages', json={'content': question}, headers=headers)
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines()]
                message = events[-1].get('message', {})
                if not isinstance(message, dict):
                    # A stream error event carries its text here; the case fails instead of aborting the run.
                    message = {'status': 'error', 'error': message, 'sources': []}
                if message.get('retrieval_run_id'):
                    trace_response = inspector.get('/admin/retrieval/runs/' + message['retrieval_run_id'])
                    trace_response.raise_for_status()
                    trace = trace_response.json()['result']
                else:
                    trace = {'chat_outcome': {'status': 'interrupted', 'reason': 'stream_error'}}
                factual = expected == 'answer'
                passed = message.get('status') == ('completed' if factual else 'abstained')
                passed &= bool(message.get('sources')) == factual
                if factual:
                    passed &= any(s['title'] == EXPECTED_TITLES[name] for s in message.get('sources', []))
                if not factual:
                    passed &= trace.get('decision', {}).get('action') == expected
                allowed = {c['chunk_id']: c for c in trace.get('results', [])}
                for source in message.get('sources', []):
                    passed &= source['chunk_id'] in allowed and source['quote'] == allowed[source['chunk_id']]['content']
                    passed &= f"[{source['citation_id']}]" in message['content']
                    download = client.get(f"/chat/messages/{message['id']}/sources/{source['citation_id']}/original")
                    passed &= download.status_code == 200
                    passed &= hashlib.sha256(download.content).hexdigest() == source['source_sha256']
                row = {'id': name, 'question': question, 'expected': expected, 'conversation_id': cid,
                       'message': message, 'trace': trace, 'passed': passed}
                print(f"{name}: {'PASS' if passed else 'FAIL'}, {trace.get('chat_outcome')}"
                      + (f", error={message['error']}" if message.get('error') else ''), flush=True)
            rows.append(row)
            (output / f'{args.scope}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        client.post('/auth/logout', headers=headers).raise_for_status()
        inspector.post('/auth/logout', headers={'Origin': origin,
            'X-CSRF-Token': inspector.get('/auth/me').json()['csrf_token']}).raise_for_status()
    if not args.search_only and not all(row['passed'] for row in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

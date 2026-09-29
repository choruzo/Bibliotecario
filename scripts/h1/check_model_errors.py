"""Prueba fallos en APIs efimeras dentro del contenedor, sin detener los modelos del host."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = """import json,os,subprocess,sys,time
import httpx
account=json.load(sys.stdin)
results={}
for service,variable in [('llm','BIB_LLM_BASE_URL'),('embedding','BIB_EMBEDDING_BASE_URL'),('reranker','BIB_RERANKER_BASE_URL')]:
    env=os.environ.copy()
    env[variable]='http://127.0.0.1:9'
    env['BIB_MODEL_TIMEOUT_SECONDS']='10'
    server=subprocess.Popen(['uvicorn','bibliotecario.main:create_app','--factory','--host','127.0.0.1','--port','8800','--no-access-log'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url='http://127.0.0.1:8800',timeout=15) as client:
            for attempt in range(40):
                try:
                    if client.get('/health/live').status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.25)
            origin=os.environ['BIB_PUBLIC_ORIGIN']
            login=client.post('/auth/login',headers={'Origin':origin},json=account)
            assert login.status_code==200, 'Login de prueba fallo'
            identity=login.json()
            response=client.get('/health/dependencies')
            checks=response.json()['checks']
            assert response.status_code==503, 'No se informo disponibilidad degradada'
            assert checks[service]['error']=='connection_error', 'Error no clasificado'
            assert all(value['status']=='available' for name,value in checks.items() if name!=service), 'Un fallo afecto a otros checks'
            assert client.post('/auth/logout',headers={'Origin':origin,'X-CSRF-Token':identity['csrf_token']}).status_code==204
            results[service]=checks
    finally:
        server.terminate()
        server.wait(timeout=10)
print(json.dumps(results))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True, type=Path)
    args = parser.parse_args()
    account = json.loads(args.credentials.read_text(encoding="utf-8"))
    result = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", CODE],
                            cwd=ROOT, input=json.dumps(account), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("La prueba de fallos de modelos no supero sus aserciones: " + result.stderr)
    checks = json.loads(result.stdout)
    output = ROOT / ".artifacts" / "h1" / "model-errors.json"
    output.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    print("Tres escenarios aprobados: HTTP 503, connection_error aislado y otros checks disponibles.")


if __name__ == "__main__":
    main()

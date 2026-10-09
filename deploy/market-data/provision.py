"""Create a separate, private PostgreSQL service without restarting Trader."""
import os
from pathlib import Path
import secrets
import subprocess
import time


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the server')
    root = Path('/srv/market-data')
    private = root / 'private'
    for path in (root, private, root / 'imports', root / 'backups'):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    password = private / 'admin_password'
    if not password.exists():
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(40) + '\n')
    password.chmod(0o600)
    command = ['docker', 'compose', '-f', '/opt/market-data/compose.yaml']
    subprocess.run(command + ['config', '--quiet'], check=True)
    subprocess.run(command + ['up', '-d'], check=True)
    for _ in range(60):
        result = subprocess.run(command + ['exec', '-T', 'postgres', 'pg_isready', '-U', 'market_admin', '-d', 'market_data'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            print('PostgreSQL ready; credentials stored privately, port bound to loopback.', flush=True)
            break
        time.sleep(1)
    else:
        raise RuntimeError('PostgreSQL did not become ready')
    with Path('/opt/market-data/schema.sql').open('rb') as source:
        subprocess.run(command + ['exec', '-T', 'postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                                  '-U', 'market_admin', '-d', 'market_data'], stdin=source, check=True)


if __name__ == '__main__':
    main()

"""Generate local-only bootstrap configuration, never replace existing secrets."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / '.env'
password = secrets.token_urlsafe(24)
with path.open('x') as file:
    file.write(
        f'SECRET_KEY={secrets.token_urlsafe(48)}\n'
        f'DATABASE_URL=postgresql://bp:{password}@127.0.0.1:15432/bp\n'
        f'POSTGRES_PASSWORD={password}\n'
        'FIRST_SUPERUSER=admin@example.com\n'
        f'FIRST_SUPERUSER_PASSWORD={secrets.token_urlsafe(24)}\n'
    )
path.chmod(0o600)
print('Created .env. Read bootstrap credentials locally; do not commit or send them.')

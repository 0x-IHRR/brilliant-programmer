"""Real synthetic training, account erasure worker and browser receipt recovery."""
import json
import os
import secrets
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session

from app.core.db import engine
from app.core.verification import token_hash
from app.models import EmailVerification, User
from tests.test_accounts import client
from tests.test_evaluations import ready
from tests.test_model_config import account
from tests.test_training import provider, stop_worker

cases = []
with tempfile.TemporaryDirectory(prefix='bp32-account-browser-') as directory:
    for index in range(2):
        path = Path(directory) / str(index)
        path.mkdir()
        source = provider.__wrapped__(path)
        supplier = next(source)
        scenario = ready.__wrapped__(path, supplier, SimpleNamespace(param=0))
        try:
            auth, run, *_ = next(scenario)
            owner = client.get('/api/v1/users/me', headers=auth).json()['id']
            other, other_auth = account()
            email = client.get('/api/v1/users/me', headers=other_auth).json()['email']
            cases.append({'token':auth['Authorization'].removeprefix('Bearer '), 'owner':owner, 'run':run, 'other':str(other), 'email':email})
        finally:
            scenario.close()
            source.close()
    extras = []
    for mode in ('me', 'verify'):
        owner, auth = account()
        user = client.get('/api/v1/users/me', headers=auth).json()
        verification = secrets.token_urlsafe(32)
        if mode == 'verify':
            with Session(engine) as session:
                row = session.get(User, owner)
                row.email_verified = False
                session.add(row)
                session.add(EmailVerification(user_id=owner, email=row.email, token_hash=token_hash(verification), sent_at=datetime.now(UTC), expires_at=datetime.now(UTC)+timedelta(minutes=30)))
                session.commit()
        extras.append({'mode':mode, 'token':auth['Authorization'].removeprefix('Bearer '), 'owner':str(owner), 'email':user['email'], 'verification':verification})
    log = (Path(directory) / 'worker.log').open('a')
    worker = subprocess.Popen([sys.executable, '-m', 'app.training.worker'], stdout=log, stderr=log)
    log.close()
    try:
        subprocess.run(['bun', 'run', '--cwd', '../frontend', 'test', 'account-erasure.spec.ts'], env={**os.environ, 'ACCOUNT_ERASURE_CASES':json.dumps(cases), 'ACCOUNT_ERASURE_EXTRAS':json.dumps(extras)}, check=True)
        with Session(engine) as session:
            for case in cases:
                assert session.get(User, uuid.UUID(case['owner'])) is None
                assert session.get(User, uuid.UUID(case['other'])) is not None
            for extra in extras:
                assert session.get(User, uuid.UUID(extra['owner'])) is None
    finally:
        stop_worker(worker)

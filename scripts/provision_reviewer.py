"""Run locally to provision a review identity; secrets never enter application settings API."""
import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--user', required=True)
parser.add_argument('--role', required=True, choices=['editor','reviewer','approver'])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
path = root / 'data' / 'review_users.json'
users = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
if any(u['id'] == args.user for u in users):
    raise SystemExit('User exists; remove old entry locally before reprovisioning')
token = secrets.token_urlsafe(32)
users.append(dict(id=args.user, role=args.role, token_sha256=hashlib.sha256(token.encode()).hexdigest()))
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(users, indent=2), encoding='utf-8')
print('Copy this token to its assigned user through your approved private channel:')
print(token)

"""Version-bound three-role review workflow with append-only audit rows."""
import hashlib
import json
import secrets
import sqlite3
import time


def _raw_digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()


def _canonical_numbers(value):
    if isinstance(value, dict):
        return {key: _canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_numbers(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def digest(payload):
    """JSON numbers with equal values must survive a browser round trip."""
    return _raw_digest(_canonical_numbers(payload))


def authenticate(users, token):
    if not token:
        raise PermissionError('请填写复核身份令牌')
    hashed = hashlib.sha256(token.encode()).hexdigest()
    for user in users:
        if secrets.compare_digest(hashed, user.get('token_sha256', '')):
            if user.get('role') not in ('editor', 'reviewer', 'approver'):
                break
            return user
    raise PermissionError('身份令牌无效或角色未配置')


class ReviewStore:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, revision INTEGER, state TEXT, payload TEXT, hash TEXT, editor TEXT, reviewer TEXT, approver TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS snapshots (document TEXT, revision INTEGER, payload TEXT, hash TEXT, PRIMARY KEY(document,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, document TEXT, revision INTEGER, actor TEXT, role TEXT, action TEXT, hash TEXT, at REAL)')

    def get(self, key):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM versions WHERE id=?', (key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['payload'] = json.loads(result['payload'])
            result['audit'] = [dict(r) for r in db.execute('SELECT * FROM audit WHERE document=? ORDER BY id', (key,))]
            return result

    def transition(self, key, action, actor, revision=0, payload=None):
        roles = {'submit': 'editor', 'review': 'reviewer', 'approve': 'approver', 'reject': 'reviewer'}
        if action not in roles or actor.get('role') != roles[action]:
            raise PermissionError('当前角色不能执行此操作')
        if not actor.get('id') or not key:
            raise ValueError('缺少用户或文档标识')
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM versions WHERE id=?', (key,)).fetchone()
            current = dict(row) if row else dict(revision=0, state='draft', editor=None, reviewer=None, approver=None)
            if type(revision) is not int or revision != current['revision']:
                raise ValueError('版本已变化，请重新加载后操作')
            if action == 'submit':
                if not isinstance(payload, dict) or not payload:
                    raise ValueError('提交内容不能为空')
                current.update(payload=json.dumps(payload, ensure_ascii=False, allow_nan=False), hash=digest(payload), editor=actor['id'], reviewer=None, approver=None, state='submitted')
            else:
                stored = json.loads(current['payload']) if current.get('payload') else None
                # Accept existing snapshots without rewriting their audit hashes.
                stored_valid = stored is not None and current.get('hash') in (digest(stored), _raw_digest(stored))
                if not isinstance(payload, dict) or not stored_valid or digest(payload) != digest(stored):
                    raise ValueError('审阅内容与待审快照不一致，请重新加载；修改内容须由编制人重新提交')
                expected = 'reviewed' if action == 'approve' else 'submitted'
                if current['state'] != expected:
                    raise ValueError('当前状态不允许此操作')
                if actor['id'] in (current['editor'], current['reviewer']):
                    raise PermissionError('编制、复核、批准必须由不同人员完成')
                current['state'] = {'review': 'reviewed', 'approve': 'approved', 'reject': 'rejected'}[action]
                current['approver' if action == 'approve' else 'reviewer'] = actor['id']
            current['revision'] += 1
            db.execute('INSERT OR REPLACE INTO versions VALUES (?,?,?,?,?,?,?,?)', (key, current['revision'], current['state'], current['payload'], current['hash'], current['editor'], current['reviewer'], current['approver']))
            db.execute('INSERT INTO snapshots VALUES (?,?,?,?)', (key,current['revision'],current['payload'],current['hash']))
            db.execute('INSERT INTO audit(document,revision,actor,role,action,hash,at) VALUES(?,?,?,?,?,?,?)', (key,current['revision'],actor['id'],actor['role'],action,current['hash'],time.time()))
        return self.get(key)

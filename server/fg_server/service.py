import hashlib
import hmac
import json
import re
import secrets
import uuid
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from .contracts import canonical, identifier

class Service:
    def __init__(self, dsn): self.dsn = dsn
    def connect(self): return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5, options='-c statement_timeout=10000')
    def migrate(self):
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(734892)')
            db.execute(Path(__file__).with_name('schema.sql').read_text())
            db.execute('ALTER TABLE nas_clients ADD COLUMN IF NOT EXISTS actor uuid REFERENCES accounts(id)')
            for nas in db.execute('SELECT digest,tenant,branch FROM nas_clients WHERE actor IS NULL').fetchall():
                actor=uuid.uuid4()
                db.execute("INSERT INTO accounts(id,tenant,branch,username,salt,verifier,role) VALUES(%s,%s,%s,%s,%s,%s,'radius')",(actor,nas['tenant'],nas['branch'],'nas-'+str(actor),secrets.token_bytes(16),secrets.token_bytes(32)))
                db.execute('UPDATE nas_clients SET actor=%s WHERE digest=%s',(actor,nas['digest']))
            db.execute('ALTER TABLE nas_clients ALTER COLUMN actor SET NOT NULL')
            db.execute('INSERT INTO schema_version VALUES(2) ON CONFLICT DO NOTHING')
    @staticmethod
    def hash_password(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    def create_account(self, tenant, branch, username, password, role):
        for value in (tenant, branch, username): identifier(value)
        if not 12 <= len(password) <= 128: raise ValueError('PASSWORD_LENGTH')
        if role not in {'owner','cashier','reader','radius'}: raise ValueError('INVALID_ROLE')
        salt = secrets.token_bytes(16)
        with self.connect() as db:
            db.execute('INSERT INTO accounts(id,tenant,branch,username,salt,verifier,role) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                       (uuid.uuid4(),tenant,branch,username,salt,self.hash_password(password,salt),role))
    def login(self, username, password):
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>120 or len(password)>128:
            raise PermissionError('INVALID_LOGIN')
        token=None
        with self.connect() as db:
            account=db.execute('SELECT *,locked_until>now() AS locked FROM accounts WHERE username=%s FOR UPDATE',(username,)).fetchone()
            salt=bytes(account['salt']) if account else bytes(16)
            computed=self.hash_password(password,salt)
            if account and account['enabled'] and not account['locked'] and hmac.compare_digest(computed,bytes(account['verifier'])):
                token=secrets.token_urlsafe(32)
                db.execute('UPDATE accounts SET failures=0,locked_until=NULL WHERE id=%s',(account['id'],))
                db.execute('DELETE FROM sessions WHERE account=%s OR expires<=now()',(account['id'],))
                db.execute("INSERT INTO sessions VALUES(%s,%s,now()+interval '15 minutes')",(hashlib.sha256(token.encode()).digest(),account['id']))
            elif account and not account['locked']:
                db.execute("UPDATE accounts SET failures=failures+1,locked_until=CASE WHEN failures>=4 THEN now()+interval '30 seconds' ELSE NULL END WHERE id=%s",(account['id'],))
        if token is None: raise PermissionError('INVALID_LOGIN')
        return token
    def logout(self, token):
        if not isinstance(token,str) or not 20<=len(token)<=100:raise PermissionError('LOGIN_REQUIRED')
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest=%s',(hashlib.sha256(token.encode()).digest(),))
    def principal(self, db, token):
        if not isinstance(token,str) or not 20<=len(token)<=100: raise PermissionError('LOGIN_REQUIRED')
        a=db.execute('SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account WHERE s.digest=%s AND s.expires>now() AND a.enabled',
                     (hashlib.sha256(token.encode()).digest(),)).fetchone()
        if not a: raise PermissionError('LOGIN_REQUIRED')
        return a
    def ingest(self, token, events, nas_key=None):
        if not isinstance(events,list) or not 1<=len(events)<=100: raise ValueError('BATCH_LIMIT')
        validated=[(e,*canonical(e)) for e in events]
        result=[]
        with self.connect() as db:
            if nas_key is None:a=self.principal(db,token)
            else:
                a=db.execute('SELECT a.* FROM nas_clients n JOIN accounts a ON a.id=n.actor WHERE n.digest=%s AND n.enabled AND a.enabled',(hashlib.sha256(nas_key.encode()).digest(),)).fetchone()
                if not a:raise PermissionError('INVALID_NAS')
            # Serialize queue admission per tenant; no unbounded backlog from concurrent requests.
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(a['tenant'],))
            for event, raw, digest in validated:
                if a['role'] not in ({'owner','cashier'} if event['kind']=='ledger.append' else {'owner','radius'}):
                    raise PermissionError('ACCESS_DENIED')
                key=(a['tenant'],a['branch'],event['id'])
                old=db.execute('SELECT digest,state FROM events WHERE tenant=%s AND branch=%s AND event_id=%s',key).fetchone()
                if old:
                    if old['digest']!=digest:
                        db.execute('INSERT INTO conflicts(tenant,branch,event_id,digest,actor) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',key+(digest,a['id']))
                        result.append({'id':event['id'],'state':'CONFLICT'})
                    else: result.append({'id':event['id'],'state':old['state']})
                    continue
                count=db.execute("SELECT count(*) AS n FROM events WHERE tenant=%s AND state='QUEUED'",(a['tenant'],)).fetchone()['n']
                if count>=10000: raise ValueError('QUEUE_FULL')
                db.execute('INSERT INTO events(tenant,branch,event_id,device,kind,digest,body,actor) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)',
                           key+(event['device'],event['kind'],digest,json.dumps(event['body']),a['id']))
                result.append({'id':event['id'],'state':'QUEUED'})
        return result
    def page(self, token, after=0):
        if type(after) is not int or after<0 or after>2**63-1: raise ValueError('INVALID_CURSOR')
        with self.connect() as db:
            a=self.principal(db,token)
            return db.execute('SELECT seq,event_id,kind,state,reason,body FROM events WHERE tenant=%s AND branch=%s AND seq>%s ORDER BY seq LIMIT 100',
                              (a['tenant'],a['branch'],after)).fetchall()
    def work(self):
        with self.connect() as db:
            # One bounded global worker avoids reordering reversals or session counters.
            if not db.execute('SELECT pg_try_advisory_xact_lock(734893) AS locked').fetchone()['locked']: return 0
            rows=db.execute("SELECT * FROM events WHERE state='QUEUED' ORDER BY seq LIMIT 100 FOR UPDATE").fetchall()
            for e in rows:
                reason=None;b=e['body'];scope=(e['tenant'],e['branch'])
                if e['kind']=='ledger.append':
                    existing=db.execute('SELECT * FROM ledger WHERE tenant=%s AND branch=%s AND id=%s',scope+(e['event_id'],)).fetchone()
                    if existing:
                        same=all(existing[k]==b[v] for k,v in [('subscriber','subscriber'),('currency','currency'),('amount','amount_minor'),('reversal_of','reversal_of'),('note','note')])
                        db.execute('UPDATE events SET state=%s,reason=%s WHERE seq=%s',('APPLIED' if same else 'QUARANTINED',None if same else 'LEDGER_CONFLICT',e['seq']))
                        continue
                    if b['reversal_of']:
                        old=db.execute('SELECT * FROM ledger WHERE tenant=%s AND branch=%s AND id=%s',scope+(b['reversal_of'],)).fetchone()
                        already=db.execute('SELECT 1 FROM ledger WHERE tenant=%s AND branch=%s AND reversal_of=%s',scope+(b['reversal_of'],)).fetchone()
                        if not old or already or old['reversal_of'] or old['subscriber']!=b['subscriber'] or old['currency']!=b['currency'] or old['amount']!=-b['amount_minor']:
                            reason='INVALID_REVERSAL'
                    currency=db.execute('SELECT currency FROM ledger WHERE tenant=%s AND branch=%s AND subscriber=%s LIMIT 1',scope+(b['subscriber'],)).fetchone()
                    if currency and currency['currency']!=b['currency']: reason='CURRENCY_CONFLICT'
                    if not reason:
                        db.execute('INSERT INTO ledger VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',scope+(e['event_id'],b['subscriber'],b['currency'],b['amount_minor'],b['reversal_of'],b['note']))
                else:
                    key=scope+(b['nas'],b['session'])
                    old=db.execute('SELECT * FROM radius_sessions WHERE tenant=%s AND branch=%s AND nas=%s AND session=%s',key).fetchone()
                    if old and (old['username']!=b['user'] or b['seconds']<old['seconds'] or b['input_octets']<old['input_octets'] or b['output_octets']<old['output_octets'] or (old['stopped'] and b['status']!='Stop')):
                        reason='ACCOUNTING_CONFLICT'
                    elif not old and b['status']!='Start': reason='MISSING_START'
                    else:
                        db.execute('INSERT INTO radius_sessions VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant,branch,nas,session) DO UPDATE SET seconds=excluded.seconds,input_octets=excluded.input_octets,output_octets=excluded.output_octets,stopped=excluded.stopped',
                                   key+(b['user'],b['seconds'],b['input_octets'],b['output_octets'],b['status']=='Stop'))
                db.execute('UPDATE events SET state=%s,reason=%s WHERE seq=%s',('QUARANTINED' if reason else 'APPLIED',reason,e['seq']))
            return len(rows)
    def provision_nas(self, tenant, branch, nas):
        for value in (tenant,branch,nas):identifier(value)
        key=secrets.token_urlsafe(32)
        with self.connect() as db:
            actor=uuid.uuid4()
            db.execute("INSERT INTO accounts(id,tenant,branch,username,salt,verifier,role) VALUES(%s,%s,%s,%s,%s,%s,'radius')",(actor,tenant,branch,'nas-'+str(actor),secrets.token_bytes(16),secrets.token_bytes(32)))
            db.execute('INSERT INTO nas_clients(digest,tenant,branch,nas,actor) VALUES(%s,%s,%s,%s,%s)',(hashlib.sha256(key.encode()).digest(),tenant,branch,nas,actor))
        return key
    def provision_radius_user(self, tenant, branch, username, password, expires):
        for value in (tenant,branch,username):identifier(value)
        if not 12<=len(password)<=128:raise ValueError('PASSWORD_LENGTH')
        salt=secrets.token_bytes(16)
        with self.connect() as db:
            db.execute('INSERT INTO radius_users(tenant,branch,username,salt,verifier,expires,enabled) VALUES(%s,%s,%s,%s,%s,%s,true) ON CONFLICT(tenant,branch,username) DO UPDATE SET salt=excluded.salt,verifier=excluded.verifier,expires=excluded.expires,enabled=true',
                       (tenant,branch,username,salt,self.hash_password(password,salt),expires))
    def radius_authenticate(self, nas_key, username, password):
        if not isinstance(nas_key,str) or not 20<=len(nas_key)<=100:raise PermissionError('INVALID_NAS')
        if not isinstance(username,str) or len(username)>120 or not isinstance(password,str) or len(password)>128:raise PermissionError('INVALID_LOGIN')
        accepted=False
        with self.connect() as db:
            nas=db.execute('SELECT * FROM nas_clients WHERE digest=%s AND enabled',(hashlib.sha256(nas_key.encode()).digest(),)).fetchone()
            if not nas:raise PermissionError('INVALID_NAS')
            key=(nas['tenant'],nas['branch'],username)
            user=db.execute('SELECT *,locked_until>now() AS locked,expires>now() AS current FROM radius_users WHERE tenant=%s AND branch=%s AND username=%s FOR UPDATE',key).fetchone()
            salt=bytes(user['salt']) if user else bytes(16)
            verifier=self.hash_password(password,salt)
            accepted=bool(user and user['enabled'] and user['current'] and not user['locked'] and hmac.compare_digest(verifier,bytes(user['verifier'])))
            if accepted:
                db.execute('UPDATE radius_users SET failures=0,locked_until=NULL WHERE tenant=%s AND branch=%s AND username=%s',key)
            elif user and not user['locked']:
                db.execute("UPDATE radius_users SET failures=failures+1,locked_until=CASE WHEN failures>=4 THEN now()+interval '30 seconds' ELSE NULL END WHERE tenant=%s AND branch=%s AND username=%s",key)
        if not accepted:raise PermissionError('INVALID_LOGIN')
        return True
    def identity(self,token):
        with self.connect() as db:
            account=self.principal(db,token)
            return {key:account[key] for key in ('tenant','branch','role')}
    def radius_accounting(self,nas_key,attributes):
        if not isinstance(nas_key,str) or not 20<=len(nas_key)<=100:raise PermissionError('INVALID_NAS')
        if not isinstance(attributes,dict):raise ValueError('INVALID_ATTRIBUTES')
        def value(name,default=None):
            item=attributes.get(name)
            if item is None:return default
            if not isinstance(item,dict) or not isinstance(item.get('value'),list) or len(item['value'])!=1:raise ValueError('INVALID_ATTRIBUTE')
            return item['value'][0]
        with self.connect() as db:
            nas=db.execute('SELECT * FROM nas_clients WHERE digest=%s AND enabled',(hashlib.sha256(nas_key.encode()).digest(),)).fetchone()
            if not nas:raise PermissionError('INVALID_NAS')
        def number(name):
            item=value(name,0)
            if type(item) is int:return item
            if isinstance(item,str) and re.fullmatch(r"[0-9]{1,19}",item):return int(item)
            raise ValueError("INVALID_COUNTER")
        def counter(low,high):
            a=number(low);b=number(high)
            if not 0<=a<=2**32-1 or not 0<=b<=2**31-1:raise ValueError('INVALID_COUNTER')
            return (b<<32)+a
        body=dict(nas=nas['nas'],session=value('Acct-Unique-Session-Id') or value('Acct-Session-Id'),user=value('User-Name'),
                  status=value('Acct-Status-Type'),seconds=number('Acct-Session-Time'),
                  input_octets=counter('Acct-Input-Octets','Acct-Input-Gigawords'),output_octets=counter('Acct-Output-Octets','Acct-Output-Gigawords'))
        raw=json.dumps(body,sort_keys=True,separators=(',',':'))
        event=dict(version=1,id='radius-'+hashlib.sha256(raw.encode()).hexdigest(),device='radius:'+hashlib.sha256(nas['nas'].encode()).hexdigest(),kind='radius.accounting',body=body)
        return self.ingest('',[event],nas_key=nas_key)

    def radius_users(self, token):
        with self.connect() as db:
            a=self.principal(db,token)
            if a['role'] not in {'owner','reader'}: raise PermissionError('ACCESS_DENIED')
            return db.execute("""SELECT u.username,u.expires,u.enabled,
                COALESCE(sum(rs.seconds),0) AS seconds,
                COALESCE(sum(rs.input_octets),0) AS input_octets,
                COALESCE(sum(rs.output_octets),0) AS output_octets,
                count(rs.session) FILTER (WHERE NOT rs.stopped) AS active_sessions
                FROM radius_users u LEFT JOIN radius_sessions rs
                ON rs.tenant=u.tenant AND rs.branch=u.branch AND rs.username=u.username
                WHERE u.tenant=%s AND u.branch=%s
                GROUP BY u.username,u.expires,u.enabled ORDER BY u.username LIMIT 2000""",
                (a['tenant'],a['branch'])).fetchall()

    def radius_sessions(self, token, active_only=False):
        with self.connect() as db:
            a=self.principal(db,token)
            if a['role'] not in {'owner','reader'}: raise PermissionError('ACCESS_DENIED')
            sql="""SELECT nas,session,username,seconds,input_octets,output_octets,stopped
                   FROM radius_sessions WHERE tenant=%s AND branch=%s"""
            args=[a['tenant'],a['branch']]
            if active_only: sql+=" AND NOT stopped"
            sql+=" ORDER BY stopped,username,nas,session LIMIT 5000"
            return db.execute(sql,args).fetchall()

    def business_sync_read(self,token):
        with self.connect() as db:
            a=self.principal(db,token)
            if a['role']!='owner':raise PermissionError('ACCESS_DENIED')
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(a['tenant'],))
            return self._business_replica(db,a)

    def _business_replica(self,db,a):
        head=db.execute('SELECT revision,digest FROM business_sync_heads WHERE tenant=%s AND branch=%s',(a['tenant'],a['branch'])).fetchone()
        records=db.execute('SELECT DISTINCT ON (kind,id) kind,id,body FROM business_sync_records WHERE tenant=%s AND branch=%s ORDER BY kind,id,revision DESC',(a['tenant'],a['branch'])).fetchall()
        return dict(revision=head['revision'] if head else 0,records=[dict(table=r['kind'],id=r['id'],body=r['body']) for r in records])

    def business_sync_write(self,token,body):
        from .business_sync import validate,preserve,digest,SyncConflict
        if not isinstance(body,dict) or set(body)!={'revision','device','records'} or type(body['revision']) is not int or not 0<=body['revision']<2**63-1:raise ValueError('SYNC_REQUEST')
        identifier(body['device'])
        with self.connect() as db:
            a=self.principal(db,token)
            if a['role']!='owner':raise PermissionError('ACCESS_DENIED')
            # Same worker lock as financial event application; then the admission lock.
            db.execute('SELECT pg_advisory_xact_lock(734893)')
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(a['tenant'],))
            incoming=validate(body['records'],a['tenant'],a['branch'])
            old=self._business_replica(db,a);existing={(r['table'],r['id']):r['body'] for r in old['records']}
            if incoming==existing:return dict(revision=old['revision'],accepted=True)
            if old['revision']!=body['revision']:raise SyncConflict('SYNC_REVISION_CONFLICT')
            preserve(existing,incoming)
            financial=db.execute('SELECT * FROM ledger WHERE tenant=%s AND branch=%s',(a['tenant'],a['branch'])).fetchall()
            for entry in financial:
                row=incoming.get(('ledger',entry['id']))
                if row is None or any(row[k]!=entry[v] for k,v in [('subscriber_id','subscriber'),('currency','currency'),('amount_minor','amount'),('reversal_of','reversal_of'),('note','note')]):raise ValueError('SYNC_LEDGER_CONFLICT')
            known={r['id'] for r in financial}
            ordered=sorted((r for (t,_),r in incoming.items() if t=='ledger' and r['id'] not in known),key=lambda r:(r['reversal_of'] is not None,r['created_at'],r['id']))
            for row in ordered:
                db.execute('INSERT INTO ledger VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(a['tenant'],a['branch'],row['id'],row['subscriber_id'],row['currency'],row['amount_minor'],row['reversal_of'],row['note']))
            revision=old['revision']+1
            for (table,key),row in incoming.items():
                if existing.get((table,key))!=row:
                    db.execute('INSERT INTO business_sync_records(tenant,branch,kind,id,revision,body,actor,device) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)',(a['tenant'],a['branch'],table,key,revision,json.dumps(row),a['id'],body['device']))
            db.execute('INSERT INTO business_sync_heads VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,branch) DO UPDATE SET revision=excluded.revision,digest=excluded.digest',(a['tenant'],a['branch'],revision,digest(body['records'])))
            return dict(revision=revision,accepted=True)

"""Bounded WSGI API. Bind to loopback; expose only through an HTTPS reverse proxy."""
from .business_sync import SyncConflict
import json
from datetime import datetime
from decimal import Decimal

def json_value(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value(): return int(value)
    raise TypeError("Unsupported response value")

class Application:
    def __init__(self, service):
        from .diagnostics import Diagnostics
        self.service=service
        self.diagnostics=Diagnostics()
    def __call__(self, env, start):
        status='200 OK'
        try:
            path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','')
            from .panel import asset
            public=asset(path,method,start)
            if public is not None:return public
            auth=env.get('HTTP_AUTHORIZATION','')
            token=auth[7:] if auth.startswith('Bearer ') else ''
            if method=='GET' and path=='/v1/radius/authenticate':
                import base64
                if not auth.startswith('Basic '):raise PermissionError('INVALID_LOGIN')
                decoded=base64.b64decode(auth[6:],validate=True).decode()
                username,password=decoded.split(':',1)
                self.service.radius_authenticate(env.get('HTTP_X_FG_NAS_KEY',''),username,password)
                status='204 No Content';result=None
            elif method=='GET' and path=='/v1/business/sync':result=self.service.business_sync_read(token)
            elif method=='GET' and path=='/v1/identity':result=self.service.identity(token)
            elif method=='GET' and path=='/v1/radius/users':result={'users':self.service.radius_users(token)}
            elif method=='GET' and path=='/v1/radius/sessions':
                from urllib.parse import parse_qs
                query=parse_qs(env.get('QUERY_STRING',''),strict_parsing=False)
                active=query.get('active',['0'])[0]=='1'
                result={'sessions':self.service.radius_sessions(token,active)}
            elif method=='GET' and path=='/health': result={'version':1}
            elif method=='POST' and path in {'/v1/login','/v1/logout','/v1/events','/v1/radius/accounting','/v1/business/sync','/v1/diagnostics'}:
                if env.get('CONTENT_TYPE','').split(';')[0]!='application/json': raise ValueError('JSON_REQUIRED')
                length=int(env.get('CONTENT_LENGTH','0'))
                if not 1<=length<=(21*1024*1024 if path=='/v1/business/sync' else 1048576): raise ValueError('BODY_LIMIT')
                raw=env['wsgi.input'].read(length)
                if len(raw)!=length: raise ValueError('INCOMPLETE_BODY')
                body=json.loads(raw)
                if path=='/v1/login':
                    if not isinstance(body,dict) or set(body)!={'username','password'}: raise ValueError('INVALID_LOGIN')
                    result={'token':self.service.login(body['username'],body['password']),'expires_in':900}
                elif path=='/v1/diagnostics':
                    if body!={}:raise ValueError('INVALID_DIAGNOSTICS')
                    if self.service.identity(token)['role'] not in {'owner','reader'}:raise PermissionError()
                    result=self.diagnostics.run(self.service)
                    if self.service.identity(token)['role'] not in {'owner','reader'}:raise PermissionError()
                elif path=='/v1/logout':
                    if body!={}:raise ValueError('INVALID_LOGOUT')
                    self.service.logout(token);status='204 No Content';result=None
                elif path=='/v1/business/sync':result=self.service.business_sync_write(token,body)
                elif path=='/v1/radius/accounting':
                    self.service.radius_accounting(env.get('HTTP_X_FG_NAS_KEY',''),body);status='204 No Content';result=None
                else: result={'events':self.service.ingest(token,body)}
            elif method=='GET' and path=='/v1/events':
                from urllib.parse import parse_qs
                query=parse_qs(env.get('QUERY_STRING',''),strict_parsing=True)
                result={'events':self.service.page(token,int(query.get('after',['0'])[0]))}
            else: status='404 Not Found';result={'error':'NOT_FOUND'}
        except SyncConflict:
            status='409 Conflict';result={'error':'SYNC_REVISION_CONFLICT'}
        except PermissionError:
            status='403 Forbidden';result={'error':'ACCESS_DENIED'}
        except (ValueError,TypeError,KeyError):
            status='400 Bad Request';result={'error':'INVALID_REQUEST'}
        except Exception:
            status='503 Service Unavailable';result={'error':'RETRY_LATER'}
        data=b'' if result is None else json.dumps(result,separators=(',',':'),default=json_value).encode()
        start(status,[('Content-Type','application/json'),('Content-Length',str(len(data))),('Cache-Control','no-store')])
        return [data]

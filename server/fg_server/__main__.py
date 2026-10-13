import argparse
import getpass
import os
import time
from wsgiref.simple_server import make_server
from .http import BoundedWSGIServer, Handler
from .service import Service
from .app import Application

parser=argparse.ArgumentParser()
parser.add_argument('command',choices=['migrate','account','serve','worker','nas','radius-user'])
parser.add_argument('--tenant');parser.add_argument('--branch');parser.add_argument('--username')
parser.add_argument('--nas');parser.add_argument('--expires')
parser.add_argument('--role',choices=['owner','cashier','reader','radius'],default='reader')
args=parser.parse_args();service=Service(os.environ['FG_DATABASE_URL'])
if args.command=='migrate': service.migrate()
elif args.command=='account':
    password=getpass.getpass('Password (12–128 characters): ')
    if password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords differ')
    service.create_account(args.tenant,args.branch,args.username,password,args.role)
elif args.command=='nas':
    print(service.provision_nas(args.tenant,args.branch,args.nas))
elif args.command=='radius-user':
    from datetime import datetime
    expires=datetime.fromisoformat(args.expires)
    if expires.tzinfo is None:raise SystemExit('Expiry needs a UTC offset')
    password=getpass.getpass('Subscriber password: ')
    if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords differ')
    service.provision_radius_user(args.tenant,args.branch,args.username,password,expires)
elif args.command=='worker':
    while True:
        service.work();time.sleep(1)
else:
    with make_server(os.environ.get('FG_BIND','127.0.0.1'),8080,Application(service),handler_class=Handler,server_class=BoundedWSGIServer) as server:
        server.serve_forever()

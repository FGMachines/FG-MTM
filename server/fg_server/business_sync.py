"""Scoped, bounded full business replica. Financial records and history are append-only."""
import hashlib
import json
from .contracts import identifier

FIELDS = {
 'organizations':'id name', 'branches':'id organization_id name',
 'subscribers':'id organization_id branch_id name phone service account currency created_at',
 'ledger':'id organization_id branch_id subscriber_id kind amount_minor currency note created_at reversal_of',
 'plans':'id organization_id branch_id name service currency price_minor days created_at',
 'invoices':'id organization_id branch_id subscriber_id plan_id customer_name plan_name amount_minor currency days starts_day ends_day paid_minor charge_id payment_id created_at',
 'invoice_voids':'id invoice_id organization_id branch_id reason created_at',
 'expenses':'id organization_id branch_id category amount_minor currency note reversal_of created_at',
 'import_batches':'id organization_id branch_id digest row_count created_at',
 'payment_details':'ledger_id method reference',
 'router_bindings':'id organization_id branch_id subscriber_id fingerprint label account_id account service profile created_at',
 'network_jobs':'id organization_id branch_id invoice_id binding_id profile end_day byte_limit created_at',
 'sales':'id organization_id branch_id subscriber_id customer items_json amount_minor currency paid_minor charge_id payment_id created_at',
 'sale_voids':'id sale_id organization_id branch_id reason created_at',
 'team_members':'id organization_id branch_id name phone role currency commission_bps active created_at',
 'reseller_entries':'id organization_id branch_id member_id kind amount_minor note sale_id reversal_of created_at',
 'audit':'organization_id branch_id entity entity_id action actor created_at detail'
}
NUMBERS=set('created_at amount_minor price_minor days starts_day ends_day paid_minor row_count end_day byte_limit commission_bps active'.split())
NULLABLE=set('reversal_of payment_id sale_id detail'.split())
CURRENCIES={'EGP','USD','EUR','SAR','AED','TRY'}
MAX=999999999999

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()

def validate(records,tenant,branch):
    if not isinstance(records,list) or len(records)>50000:raise ValueError('SYNC_LIMIT')
    if len(canonical(records).encode())>20*1024*1024:raise ValueError('SYNC_LIMIT')
    index={}
    for record in records:
        if not isinstance(record,dict) or set(record)!={'table','id','body'}:raise ValueError('SYNC_RECORD')
        table=record['table']; identifier(record['id'])
        if not isinstance(table,str) or table not in FIELDS:raise ValueError('SYNC_TABLE')
        body=record['body']
        if not isinstance(body,dict) or set(body)!=set(FIELDS[table].split()):raise ValueError('SYNC_FIELDS')
        key=(table,record['id'])
        if key in index:raise ValueError('SYNC_DUPLICATE')
        index[key]=body
        for name,value in body.items():
            if value is None and name in NULLABLE:continue
            if name=='detail':
                if not isinstance(value,dict) or set(value)!={'device','before_value','after_value'} or not isinstance(value['device'],str):raise ValueError('SYNC_AUDIT')
                if any(v is not None and (not isinstance(v,str) or len(v)>32000) for v in value.values()):raise ValueError('SYNC_AUDIT')
            elif name in NUMBERS:
                if type(value) is not int or abs(value)>2**63-1:raise ValueError('SYNC_NUMBER')
            elif not isinstance(value,str) or len(value)>32000:raise ValueError('SYNC_TEXT')
        if 'organization_id' in body and body['organization_id']!=tenant:raise PermissionError('SYNC_TENANT')
        if 'branch_id' in body and body['branch_id']!=branch:raise PermissionError('SYNC_BRANCH')
        if table=='organizations' and body['id']!=tenant:raise PermissionError('SYNC_TENANT')
        if table=='branches' and body['id']!=branch:raise PermissionError('SYNC_BRANCH')
        if table!='audit' and body.get('id',body.get('ledger_id'))!=record['id']:raise ValueError('SYNC_ID')
        if 'currency' in body and body['currency'] not in CURRENCIES:raise ValueError('SYNC_CURRENCY')
        if 'created_at' in body and body['created_at']<0:raise ValueError('SYNC_DATE')
        required={'subscribers':('name',),'plans':('name',),'team_members':('name',),'ledger':('note',),'invoice_voids':('reason',),'sale_voids':('reason',),'expenses':('category','note'),'reseller_entries':('note',)}
        if any(not body[name] for name in required.get(table,())):raise ValueError('SYNC_EMPTY_TEXT')
        if table=='plans' and len(body['name'])>120:raise ValueError('SYNC_PLAN')
        if 'service' in body and body['service'] not in ({'HOTSPOT','PPPOE'} if table=='router_bindings' else {'HOTSPOT','PPPOE','OTHER'}):raise ValueError('SYNC_SERVICE')

        for name in ('amount_minor','price_minor'):
            if name in body and not 1<=abs(body[name])<=MAX:raise ValueError('SYNC_MONEY')
    if ('organizations',tenant) not in index or ('branches',branch) not in index:raise ValueError('SYNC_SCOPE_MISSING')
    def ref(table,key):
        value=index.get((table,key))
        if value is None:raise ValueError('SYNC_REFERENCE')
        return value
    reversals=set()
    for (table,key),b in index.items():
        if table in {'ledger','invoices','sales','router_bindings'}:sub=ref('subscribers',b['subscriber_id'])
        if table=='ledger':
            if b['kind'] not in {'CHARGE','PAYMENT','REVERSAL'} or sub['currency']!=b['currency']:raise ValueError('SYNC_LEDGER')
            if b['kind']=='CHARGE' and (b['amount_minor']<0 or b['reversal_of']):raise ValueError('SYNC_LEDGER')
            if b['kind']=='PAYMENT' and (b['amount_minor']>0 or b['reversal_of']):raise ValueError('SYNC_LEDGER')
        if table in {'ledger','expenses','reseller_entries'} and b['reversal_of'] is not None:
            old=ref(table,b['reversal_of']);identity=('subscriber_id','currency') if table=='ledger' else ('currency','category') if table=='expenses' else ('member_id',)
            if old['reversal_of'] is not None or old['amount_minor']!=-b['amount_minor'] or any(old.get(k)!=b.get(k) for k in identity) or (table,b['reversal_of']) in reversals:raise ValueError('SYNC_REVERSAL')
            reversals.add((table,b['reversal_of']))
        elif table=='ledger' and b['kind']=='REVERSAL':raise ValueError('SYNC_REVERSAL')
        if table=='expenses' and ((b['reversal_of'] is None and b['amount_minor']<0) or (b['reversal_of'] is not None and b['amount_minor']>0)):raise ValueError('SYNC_EXPENSE')
        if table=='plans' and not (1<=b['days']<=3660 and b['price_minor']>0):raise ValueError('SYNC_PLAN')
        if table in {'invoices','sales'}:
            charge=ref('ledger',b['charge_id'])
            if charge['kind']!='CHARGE' or charge['subscriber_id']!=b['subscriber_id'] or charge['amount_minor']!=b['amount_minor'] or charge['currency']!=b['currency'] or not 0<=b['paid_minor']<=b['amount_minor']:raise ValueError('SYNC_CHARGE')
            if b['paid_minor']:
                paid=ref('ledger',b['payment_id'])
                if paid['kind']!='PAYMENT' or paid['subscriber_id']!=b['subscriber_id'] or paid['amount_minor']!=-b['paid_minor'] or paid['currency']!=b['currency']:raise ValueError('SYNC_PAYMENT')
            elif b['payment_id'] is not None:raise ValueError('SYNC_PAYMENT')
            if table=='invoices':
                plan=ref('plans',b['plan_id'])
                if not(1<=b['days']<=3660 and b['starts_day']>=0 and b['ends_day']==b['starts_day']+b['days'] and b['ends_day']<=365241780471 and b['days']==plan['days'] and b['amount_minor']==plan['price_minor'] and b['currency']==plan['currency'] and sub['service']==plan['service']):raise ValueError('SYNC_INVOICE')
            else:
                lines=json.loads(b['items_json'])
                if not isinstance(lines,list) or not 1<=len(lines)<=30:raise ValueError('SYNC_SALE')
                total=0
                for line in lines:
                    if not isinstance(line,dict) or set(line)!={'name','quantity','unitMinor'} or not isinstance(line['name'],str) or not 1<=len(line['name'])<=120 or type(line['quantity']) is not int or type(line['unitMinor']) is not int or not 1<=line['quantity']<=10000 or not 1<=line['unitMinor']<=MAX:raise ValueError('SYNC_SALE')
                    total+=line['quantity']*line['unitMinor']
                if total!=b['amount_minor']:raise ValueError('SYNC_SALE')
        if table=='payment_details':
            if ref('ledger',b['ledger_id'])['kind']!='PAYMENT' or b['method'] not in {'CASH','VODAFONE_CASH','INSTAPAY','BANK','OTHER'}:raise ValueError('SYNC_PAYMENT_METHOD')
        if table in {'invoice_voids','sale_voids'}:ref('invoices' if table=='invoice_voids' else 'sales',b['invoice_id' if table=='invoice_voids' else 'sale_id'])
        if table=='router_bindings' and (b['service']!=sub['service'] or b['account']!=sub['account']):raise ValueError('SYNC_BINDING')
        if table=='network_jobs':
            invoice=ref('invoices',b['invoice_id']);binding=ref('router_bindings',b['binding_id'])
            if invoice['subscriber_id']!=binding['subscriber_id'] or invoice['ends_day']!=b['end_day'] or b['byte_limit']<0:raise ValueError('SYNC_JOB')
        if table=='team_members' and (b['active'] not in (0,1) or not 0<=b['commission_bps']<=10000 or b['role'] not in {'ADMIN','MANAGER','TECHNICIAN','CASHIER','RESELLER','READ_ONLY'}):raise ValueError('SYNC_TEAM')
        if table=='reseller_entries':
            member=ref('team_members',b['member_id'])
            if member['role']!='RESELLER' or b['kind'] not in {'DEPOSIT','WITHDRAWAL','COMMISSION','REVERSAL'}:raise ValueError('SYNC_WALLET')
            if (b['kind']=='REVERSAL')!=(b['reversal_of'] is not None):raise ValueError('SYNC_WALLET')
            if b['kind'] in {'DEPOSIT','COMMISSION'} and b['amount_minor']<0 or b['kind']=='WITHDRAWAL' and b['amount_minor']>0:raise ValueError('SYNC_WALLET')
            if b['kind']=='COMMISSION':
                sale=ref('sales',b['sale_id'])
                if sale['currency']!=member['currency'] or b['amount_minor']!=sale['paid_minor']*member['commission_bps']//10000:raise ValueError('SYNC_COMMISSION')
            elif b['sale_id'] is not None:raise ValueError('SYNC_WALLET')
    wallets={};commissions=set();voided_invoices=set();voided_sales=set()
    for (table,key),b in index.items():
        if table=='invoice_voids':
            if b['invoice_id'] in voided_invoices:raise ValueError('SYNC_DUPLICATE_VOID')
            voided_invoices.add(b['invoice_id'])
        if table=='sale_voids':
            if b['sale_id'] in voided_sales:raise ValueError('SYNC_DUPLICATE_VOID')
            voided_sales.add(b['sale_id'])
        if table=='reseller_entries':
            wallets[b['member_id']]=wallets.get(b['member_id'],0)+b['amount_minor']
            if b['kind']=='COMMISSION':
                if b['sale_id'] in commissions:raise ValueError('SYNC_DUPLICATE_COMMISSION')
                commissions.add(b['sale_id'])
    if any(not 0<=balance<=MAX for balance in wallets.values()):raise ValueError('SYNC_WALLET_BALANCE')
    for (table,key),b in index.items():
        if table=='reseller_entries' and b['kind']=='COMMISSION' and b['sale_id'] in voided_sales and ('reseller_entries',key) not in reversals:raise ValueError('SYNC_COMMISSION_REVERSAL')
        if table in {'invoices','sales'}:
            void_table,foreign=('invoice_voids','invoice_id') if table=='invoices' else ('sale_voids','sale_id')
            canceled=key in (voided_invoices if table=='invoices' else voided_sales)
            reversed_charge=('ledger',b['charge_id']) in reversals
            reversed_payment=b['payment_id'] is None or ('ledger',b['payment_id']) in reversals
            if canceled and not(reversed_charge and reversed_payment) or not canceled and (reversed_charge or b['payment_id'] is not None and ('ledger',b['payment_id']) in reversals):raise ValueError('SYNC_PARTIAL_VOID')
    return index

def preserve(old,new):
    for key,body in old.items():
        replacement=new.get(key)
        if replacement is None:raise ValueError('SYNC_DELETE_FORBIDDEN')
        if key[0]=='team_members':
            if any(replacement[k]!=v for k,v in body.items() if k!='active'):raise ValueError('SYNC_IMMUTABLE')
        elif replacement!=body:raise ValueError('SYNC_IMMUTABLE')

class SyncConflict(Exception):pass

"""Version 1 wire contracts. Money is immutable integer minor units, never floats."""
import hashlib
import json
import re
import uuid

CURRENCIES = {'EGP', 'USD', 'EUR', 'SAR', 'AED', 'TRY'}

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,120}', value):
        raise ValueError('INVALID_ID')
    return value

def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('INVALID_INTEGER')
    return value

def canonical(event):
    if not isinstance(event, dict) or event.get('version') != 1:
        raise ValueError('UNSUPPORTED_VERSION')
    common = {'version', 'id', 'device', 'kind', 'body'}
    if set(event) != common:
        raise ValueError('INVALID_FIELDS')
    identifier(event['id']); identifier(event['device'])
    kind = event['kind']; body = event['body']
    if not isinstance(body, dict):
        raise ValueError('INVALID_BODY')
    if kind == 'ledger.append':
        if set(body) != {'subscriber', 'currency', 'amount_minor', 'reversal_of', 'note'}:
            raise ValueError('INVALID_LEDGER')
        identifier(body['subscriber'])
        integer(body['amount_minor'], -999999999999, 999999999999)
        if not body['amount_minor'] or body['currency'] not in CURRENCIES:
            raise ValueError('INVALID_MONEY')
        if body['reversal_of'] is not None: identifier(body['reversal_of'])
        if not isinstance(body['note'], str) or not 1 <= len(body['note']) <= 500:
            raise ValueError('INVALID_NOTE')
    elif kind == 'radius.accounting':
        if set(body) != {'nas', 'session', 'user', 'status', 'seconds', 'input_octets', 'output_octets'}:
            raise ValueError('INVALID_ACCOUNTING')
        for key in ('nas', 'session', 'user'): identifier(body[key])
        if body['status'] not in {'Start', 'Interim-Update', 'Stop'}:
            raise ValueError('INVALID_STATUS')
        for key in ('seconds', 'input_octets', 'output_octets'): integer(body[key], 0, 2**63-1)
    else:
        raise ValueError('UNSUPPORTED_KIND')
    raw = json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if len(raw.encode()) > 8192: raise ValueError('EVENT_TOO_LARGE')
    return raw, hashlib.sha256(raw.encode()).hexdigest()

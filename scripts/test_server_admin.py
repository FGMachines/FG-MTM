import hashlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("admin", Path(__file__).with_name("server-admin.py"))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)
contracts = types.ModuleType("fg_server.contracts")
def identifier(value):
    if not value or len(value) > 120:
        raise ValueError("Invalid identifier")
contracts.identifier = identifier
sys.modules["fg_server"] = types.ModuleType("fg_server")
sys.modules["fg_server.contracts"] = contracts

class Database:
    def __init__(self, row):
        self.row = row
        self.statements = []
        self.committed = False
        self.fail_delete = False
    def __enter__(self): return self
    def __exit__(self, kind, value, tb):
        self.committed = kind is None
    def execute(self, sql, args):
        self.statements.append((sql, args))
        if self.fail_delete and sql.startswith("DELETE"):
            raise RuntimeError("Simulated database failure")
        return self
    def fetchone(self): return self.row

class Service:
    def __init__(self, row): self.db = Database(row)
    def connect(self): return self.db
    @staticmethod
    def hash_password(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)

class RecoveryTests(unittest.TestCase):
    def test_scoped_reset_revokes_sessions_and_uses_existing_hash(self):
        s = Service({"id":"account-id","enabled":True})
        admin.reset_password(s, "tenant", "branch", "owner", "Long recovery password!")
        self.assertTrue(s.db.committed)
        select, update, delete = s.db.statements
        self.assertIn("FOR UPDATE", select[0])
        self.assertEqual(("tenant","branch","owner"), select[1])
        salt, verifier, identity = update[1]
        self.assertEqual(16, len(salt))
        self.assertEqual(s.hash_password("Long recovery password!",salt), verifier)
        self.assertEqual("account-id", identity)
        self.assertEqual(("account-id",), delete[1])
        self.assertNotIn("enabled=", update[0])
        self.assertNotIn("role=", update[0])
    def test_missing_and_disabled_do_not_update(self):
        for row in [None, {"id":"a","enabled":False}]:
            s = Service(row)
            with self.assertRaises(ValueError):
                admin.reset_password(s,"t","b","u","Long recovery password!")
            self.assertEqual(1,len(s.db.statements))
            self.assertFalse(s.db.committed)
    def test_short_password_never_opens_transaction(self):
        s = Service({"id":"a","enabled":True})
        with self.assertRaises(ValueError):
            admin.reset_password(s,"t","b","u","short")
        self.assertEqual([],s.db.statements)
    def test_delete_failure_does_not_commit(self):
        s = Service({"id":"a","enabled":True})
        s.db.fail_delete = True
        with self.assertRaises(RuntimeError):
            admin.reset_password(s,"t","b","u","Long recovery password!")
        self.assertFalse(s.db.committed)

if __name__ == "__main__": unittest.main()

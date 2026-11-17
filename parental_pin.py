"""Beskyt appens indstillinger med PIN og en valgfri gendannelseskode.

Beskyttelsen gælder appens brugerflade. En Windows-administrator eller en
bruger, der kan ændre appens datafiler, kan omgå den.
"""
from pathlib import Path
import hashlib
import hmac
import json
import math
import os
import secrets
import tempfile
import time

ITERATIONS = 600_000
MAX_FAILURES = 5
LOCK_SECONDS = 30


class PinStoreError(RuntimeError):
    """PIN-data kan ikke læses eller gemmes. Indstillinger skal forblive låst."""


class PinStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        try:
            self._seen_protected = self.path.exists()
        except OSError:
            self._seen_protected = True

    @staticmethod
    def _valid_pin(pin):
        return isinstance(pin, str) and 4 <= len(pin) <= 12 and pin.isascii() and pin.isdigit()

    @classmethod
    def _require_pin(cls, pin):
        if not cls._valid_pin(pin):
            raise ValueError('PIN skal være 4 til 12 cifre.')

    @staticmethod
    def _hash(secret):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', secret.encode('ascii'), salt, ITERATIONS)
        return {'salt': salt.hex(), 'digest': digest.hex(), 'iterations': ITERATIONS}

    @staticmethod
    def _valid_record(record):
        if not isinstance(record, dict):
            return False
        iterations = record.get('iterations')
        if type(iterations) is not int or not 100_000 <= iterations <= 2_000_000:
            return False
        try:
            return (isinstance(record['salt'], str) and len(record['salt']) == 32
                    and len(bytes.fromhex(record['salt'])) == 16
                    and isinstance(record['digest'], str) and len(record['digest']) == 64
                    and len(bytes.fromhex(record['digest'])) == 32)
        except (KeyError, TypeError, ValueError):
            return False

    def _read(self):
        try:
            with self.path.open(encoding='utf-8') as source:
                raw = source.read(16_385)
                if len(raw) > 16_384:
                    raise PinStoreError('PIN-filen er beskadiget. Indstillingerne forbliver låst.')
                data = json.loads(raw)
        except FileNotFoundError as error:
            if self._seen_protected:
                raise PinStoreError('PIN-filen mangler. Indstillingerne forbliver låst.') from error
            return None
        except (OSError, ValueError, UnicodeError, RecursionError) as error:
            raise PinStoreError('PIN-filen kunne ikke læses. Indstillingerne forbliver låst.') from error
        self._seen_protected = True
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
            raise PinStoreError('PIN-filen er beskadiget. Indstillingerne forbliver låst.')
        recovery = data.get('recovery')
        failures = data.get('failed_attempts')
        blocked = data.get('blocked_until')
        if ('recovery' not in data or not self._valid_record(data.get('pin'))
                or recovery is not None and not self._valid_record(recovery)
                or type(failures) is not int or not 0 <= failures < MAX_FAILURES
                or type(blocked) not in (int, float) or not math.isfinite(blocked) or blocked < 0):
            raise PinStoreError('PIN-filen er beskadiget. Indstillingerne forbliver låst.')
        return data

    def _write(self, data):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix=f'.{self.path.name}.', suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                os.chmod(temporary, 0o600)
                json.dump(data, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
            self._seen_protected = True
        except (OSError, ValueError) as error:
            raise PinStoreError('PIN-data kunne ikke gemmes. Indstillingerne forbliver låst.') from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @property
    def configured(self):
        try:
            return self._read() is not None
        except PinStoreError:
            return True

    @property
    def damaged(self):
        try:
            self._read()
            return False
        except PinStoreError:
            return True

    @property
    def recovery_enabled(self):
        data = self._read()
        return data is not None and data['recovery'] is not None

    @property
    def remaining_lock_seconds(self):
        data = self._read()
        return max(0, math.ceil(data['blocked_until'] - self.clock())) if data else 0

    @staticmethod
    def _new_recovery():
        raw = secrets.token_hex(16).upper()
        return '-'.join(raw[index:index + 4] for index in range(0, len(raw), 4))

    @staticmethod
    def _normalize_recovery(code):
        if not isinstance(code, str):
            return None
        normalized = code.replace('-', '').replace(' ', '').upper()
        if len(normalized) != 32 or any(char not in '0123456789ABCDEF' for char in normalized):
            return None
        return normalized

    def setup(self, pin, *, enable_recovery=False):
        self._require_pin(pin)
        if self.configured:
            raise PermissionError('PIN er allerede oprettet. Brug den eksisterende PIN til ændringer.')
        recovery = self._new_recovery() if enable_recovery else None
        self._write({'version': 1, 'pin': self._hash(pin),
                     'recovery': self._hash(self._normalize_recovery(recovery)) if recovery else None,
                     'failed_attempts': 0, 'blocked_until': 0.0})
        return recovery

    def _authenticate(self, candidate, kind):
        data = self._read()
        if data is None or data['blocked_until'] > self.clock():
            return None
        record = data[kind]
        matched = False
        if candidate is not None and record is not None:
            digest = hashlib.pbkdf2_hmac('sha256', candidate.encode('ascii'),
                                         bytes.fromhex(record['salt']), record['iterations'])
            matched = hmac.compare_digest(digest, bytes.fromhex(record['digest']))
        if matched:
            data['failed_attempts'] = 0
            data['blocked_until'] = 0.0
        else:
            data['failed_attempts'] += 1
            if data['failed_attempts'] >= MAX_FAILURES:
                data['failed_attempts'] = 0
                data['blocked_until'] = self.clock() + LOCK_SECONDS
        self._write(data)
        return data if matched else None

    def verify(self, pin):
        candidate = pin if self._valid_pin(pin) else None
        return self._authenticate(candidate, 'pin') is not None

    def change_pin(self, old_pin, new_pin):
        self._require_pin(new_pin)
        data = self._authenticate(old_pin if self._valid_pin(old_pin) else None, 'pin')
        if data is None:
            raise PermissionError('Forkert PIN, eller ventetiden er ikke udløbet.')
        data['pin'] = self._hash(new_pin)
        self._write(data)

    def clear(self, pin):
        if not self.verify(pin):
            raise PermissionError('Forkert PIN, eller ventetiden er ikke udløbet.')
        try:
            self.path.unlink()
        except OSError as error:
            raise PinStoreError('PIN kunne ikke fjernes. Indstillingerne forbliver låst.') from error
        self._seen_protected = False

    def recover(self, code, new_pin):
        self._require_pin(new_pin)
        data = self._authenticate(self._normalize_recovery(code), 'recovery')
        if data is None:
            raise PermissionError('Forkert gendannelseskode, eller ventetiden er ikke udløbet.')
        replacement = self._new_recovery()
        data['pin'] = self._hash(new_pin)
        data['recovery'] = self._hash(self._normalize_recovery(replacement))
        self._write(data)
        return replacement

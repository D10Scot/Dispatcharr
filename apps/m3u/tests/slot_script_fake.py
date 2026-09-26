"""An in-memory stand-in for apps/m3u/connection_pool.py's provider-slot Lua script.

connection_pool runs every counter write through one Lua script (#513). The
in-memory Redis fakes several test modules use cannot run Lua, so they gain
``register_script`` from ``SlotScriptFakeMixin`` below, which answers the
script's four ops in Python on top of the fake's own ``get``/``set``/``delete``.

This is a second implementation of the script, and a second implementation
proves only itself. It is kept honest by
``apps/m3u/tests/test_slot_script.py``'s ``SlotScriptFakeParityTests``, which
drives the same operation sequences through the real Lua on a live Redis and
through this class, and requires identical returns and identical final state.
Atomicity is NOT something this fake can show: the real-Redis tests in that
module are what pin it.

Test routing: ``dispatcharr/test_discovery.py``'s ``_PATH_ALIASES`` sends an
edit to this file to every label whose fakes import it, because a change here
can break a label the edit never touches.
"""

from apps.m3u.connection_pool import _SLOT_SCRIPT, SLOT_VERSION_KEY_PREFIX


def _text(value):
    if isinstance(value, bytes):
        return value.decode()
    return value


class _FakeSlotScript:
    def __init__(self, redis):
        self._redis = redis

    def _read(self, key):
        value = _text(self._redis.get(key))
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

    def _write(self, key, value):
        self._redis.set(key, value)
        vkey = SLOT_VERSION_KEY_PREFIX + key
        self._redis.set(vkey, self._read(vkey) + 1)

    def _give_back(self, key):
        current = self._read(key)
        if current > 0:
            self._write(key, current - 1)
        elif current < 0:
            self._write(key, 0)

    def _take(self, key):
        current = max(self._read(key), 0)
        self._write(key, current + 1)

    def __call__(self, keys=(), args=(), client=None):
        keys = list(keys)
        args = [str(a) for a in args]
        op = args[0]
        if op == "reserve":
            pmax, cmax = int(args[1]), int(args[2])
            pc = 0
            if pmax > 0:
                pc = max(self._read(keys[0]), 0)
                if pc + 1 > pmax:
                    return [0, pc, "profile_full"]
            cc = 0
            if cmax > 0:
                cc = max(self._read(keys[1]), 0)
                if cc + 1 > cmax:
                    return [0, pc, "credential_full"]
            if pmax > 0:
                self._write(keys[0], pc + 1)
            if cmax > 0:
                self._write(keys[1], cc + 1)
                self._redis.set(keys[2], keys[1])
            return [1, pc + 1 if pmax > 0 else 0, ""]
        if op == "release":
            cred_key = _text(self._redis.get(keys[1]))
            if cred_key:
                self._give_back(cred_key)
                self._redis.delete(keys[1])
            self._give_back(keys[0])
            return 1 if cred_key else 0
        if op == "switch":
            if args[2] == "1":
                ncmax = int(args[3])
                ncc = 0
                if ncmax > 0:
                    ncc = max(self._read(keys[5]), 0)
                    if ncc + 1 > ncmax:
                        return [0, "credential_full"]
                old_cred_key = _text(self._redis.get(keys[3]))
                if old_cred_key:
                    self._give_back(old_cred_key)
                    self._redis.delete(keys[3])
                if ncmax > 0:
                    self._write(keys[5], ncc + 1)
                    self._redis.set(keys[4], keys[5])
            self._give_back(keys[0])
            self._redis.set(keys[2], args[1])
            self._take(keys[1])
            return [1, ""]
        if op == "reconcile":
            key = keys[0]
            version = self._read(SLOT_VERSION_KEY_PREFIX + key)
            current = self._read(key)
            if version != int(args[1]):
                return [-1, current, current]
            target = min(max(current, int(args[2])), int(args[3]))
            if target == current:
                return [0, current, current]
            self._redis.set(key, target)
            return [1, current, target]
        raise ValueError(f"provider_slot: unknown op {op}")


class SlotScriptFakeMixin:
    """Gives an in-memory Redis fake the one ``register_script`` connection_pool needs."""

    def register_script(self, source):
        if source != _SLOT_SCRIPT:
            raise NotImplementedError(
                "SlotScriptFakeMixin answers only connection_pool's slot script"
            )
        return _FakeSlotScript(self)

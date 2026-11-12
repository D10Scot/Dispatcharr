"""The mutex behind "an active admin always remains" (SSO spec section 4.4, D21).

``admin_floor_lock()`` is a PostgreSQL transaction-scoped advisory lock over "writes that
can remove an active admin". It locks no row. Callers: PR S0's deactivation guard
(``UserViewSet.perform_update``); S2's SSO callback and token refresh take the same lock.

The floor protocol every caller follows:

1. ``admin_floor_lock()``, as the transaction's first statement.
2. (callback only) the identity row.
3. Reload and lock the target: ``User.objects.select_for_update().get(pk=...)``.
4. Decide on that reloaded row, never on an object loaded before step 1.
5. Write.

Key choice
----------
``ADMIN_FLOOR_LOCK_KEY`` is a fixed bigint, the ASCII bytes of ``MINOADM1``. It is a
constant on purpose: every process must derive the same key. Nothing else in the tree
takes an advisory lock (``grep -rn advisory`` is empty apart from this module), so a
collision would need another application sharing the database to pick the same 64 bits.

django-db-geventpool
--------------------
uWSGI runs the ``django-db-geventpool`` backend. Its ``get_new_connection`` takes one
real connection from the pool for the greenlet's Django connection and keeps it until
``close()``, which only returns it to the pool; inside ``transaction.atomic()`` that
is the whole block, so ``pg_advisory_xact_lock`` is taken and released on one server
session. Because the lock is the ``xact`` variant it is dropped at COMMIT or ROLLBACK
and cannot leak onto a pooled connection, which is why the session-level variant is not
used. psycopg 3 switches to a gevent-cooperative wait function when ``select`` is
monkey-patched (``psycopg/waiting.py`` ``_is_select_patched``), so a greenlet waiting for
the lock yields the hub rather than blocking it.
"""

from django.db import connection

ADMIN_FLOOR_LOCK_KEY = 0x4D494E4F41444D31  # b"MINOADM1"


def admin_floor_lock():
    """Take the admin-floor advisory lock for the current transaction.

    Must be called inside ``transaction.atomic()``. A no-op on a database other than
    PostgreSQL: the test fallback (``TEST_USE_SQLITE=1``) has nothing to serialize and the
    tests that depend on the lock skip themselves; a runtime SQLite instance is refused
    before it gets here (``settings.RUNTIME_SQLITE``).
    """
    if connection.vendor != "postgresql":
        return
    if not connection.in_atomic_block:
        raise RuntimeError("admin_floor_lock() must be called inside transaction.atomic()")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMIN_FLOOR_LOCK_KEY])

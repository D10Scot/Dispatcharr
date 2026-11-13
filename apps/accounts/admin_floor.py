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

The bounded wait
----------------
``pg_advisory_xact_lock`` itself waits forever. Each waiter holds one of its uWSGI
worker's eight pooled connections, so a holder that stalls would otherwise be bounded
only by the 120 s ``harakiri``, which kills the whole worker and every other request on
it. The helper therefore sets ``lock_timeout`` to ``LOCK_WAIT_SECONDS`` with
``SET LOCAL`` immediately before the lock, and puts the previous value back (read
first, never assumed to be 0) immediately after the lock is granted, so the bound covers
the advisory lock only: the row locks a caller takes afterwards (``select_for_update``)
wait exactly as they did before. When the bound passes PostgreSQL raises SQLSTATE
``55P03`` (``lock_not_available``) and aborts the transaction; the helper raises
``AdminFloorBusy`` from it and the caller's ``atomic()`` rolls back. Nothing is written.
"""

from django.db import OperationalError, connection

ADMIN_FLOOR_LOCK_KEY = 0x4D494E4F41444D31  # b"MINOADM1"
# How long a caller waits for the lock before ``AdminFloorBusy``. A module constant on
# purpose (not a setting): it bounds a wait that is otherwise bounded only by harakiri.
LOCK_WAIT_SECONDS = 5
LOCK_NOT_AVAILABLE = "55P03"


class AdminFloorBusy(OperationalError):
    """The admin-floor lock was not granted within ``LOCK_WAIT_SECONDS``.

    A ``DatabaseError`` (the transaction is aborted, exactly as for any lock timeout), so a
    caller that already maps database errors to a fixed answer reaches it unchanged; a
    caller that answers differently catches this class. It carries no message and no data:
    ``__cause__`` is the driver's error, whose ``sqlstate`` is ``55P03``.
    """

    def __init__(self):
        super().__init__("admin_floor_busy")


def admin_floor_lock():
    """Take the admin-floor advisory lock for the current transaction.

    Must be called inside ``transaction.atomic()``. Raises ``AdminFloorBusy`` when the lock
    is not granted within ``LOCK_WAIT_SECONDS``; the transaction is then aborted and must
    be left to roll back. A no-op on a database other than PostgreSQL: the test fallback
    (``TEST_USE_SQLITE=1``) has nothing to serialize and the tests that depend on the lock
    skip themselves; a runtime SQLite instance is refused before it gets here
    (``settings.RUNTIME_SQLITE``).
    """
    if connection.vendor != "postgresql":
        return
    if not connection.in_atomic_block:
        raise RuntimeError("admin_floor_lock() must be called inside transaction.atomic()")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('lock_timeout')")
        previous = cursor.fetchone()[0]
        cursor.execute(f"SET LOCAL lock_timeout = '{int(LOCK_WAIT_SECONDS * 1000)}ms'")
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMIN_FLOOR_LOCK_KEY])
        except OperationalError as exc:
            if getattr(exc.__cause__, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            raise AdminFloorBusy() from exc.__cause__
        # set_config(..., true) is SET LOCAL with a bound parameter.
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [previous])

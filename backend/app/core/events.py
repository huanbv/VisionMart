"""DEAD FILE — DO NOT USE. Kept only because this sandbox's tools could not
delete it; please delete it manually (`git rm backend/app/core/events.py`)
the next time you're on a machine with normal file access.

Why this file must not define anything: `app/core/events/` (a package,
sibling directory) already exists in this project and is wired into
`app/dependencies/providers.py` (`get_event_bus()` -> `InMemoryEventBus`).
Python's import system resolves the *package* `app/core/events/` for
`import app.core.events`, never this file — verified by direct execution
during the pre-production audit. A previous session added this file without
noticing the existing package, which caused `from app.core.events import
event_bus` (used by cart_service.py / checkout_service.py at the time) to
raise ImportError at process startup, since the package's `__init__.py`
does not export a name called `event_bus`.

The fix applied: `app/modules/sales/domain/events.py` and the sales
application services now build/publish `app.core.events.DomainEvent`
instances (the real, package one) via the injected `EventBus`
(`app/dependencies/providers.get_event_bus`) instead of importing anything
from this file. This file is intentionally left empty of any definitions so
that even if some future code accidentally imports it directly by full
path (not just `app.core.events`, which will keep resolving to the
package), there is nothing here to collide with or shadow.
"""

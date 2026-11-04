"""``python -m askcert``: delegates to :mod:`askcert.cli`."""

from importlib import import_module

raise SystemExit(import_module(".cli", __package__).main())

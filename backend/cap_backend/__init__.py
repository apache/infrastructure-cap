"""CAP backend package.

Importing this module does not construct an application; call
:func:`cap_backend.app.build_app` explicitly to do that.
"""

from cap_backend.app import build_app

__all__ = ["build_app"]

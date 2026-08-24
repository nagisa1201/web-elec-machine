"""Embedded voltage-monitoring web server and UI for the RDK X5.

The package is layered so each module can be understood and tested on its own:

* ``config``    — runtime configuration (CLI > environment > defaults)
* ``datastore`` — read-only SQLite access, minute series, daily statistics
* ``poller``    — optional in-process DL/T 645 acquisition thread (TCP)
* ``server``    — standard-library HTTP server and JSON API
* ``static``    — self-contained dashboard (HTML/CSS/JS, no CDN)

The acquisition protocol itself lives in the sibling ``host/`` package; this
package only *consumes* the SQLite store it produces and reuses the frame
converter, never modifies it.
"""

from __future__ import annotations

__version__ = "1.0.0"

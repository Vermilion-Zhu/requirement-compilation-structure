"""Gates for tests written against earlier tool, wiring and trigger contracts.

The compiler moved three contracts after these tests were written:

* ``edit_file`` rejects replacing a whole existing file (incremental spans only),
* API/page/trigger wiring is model-owned (the ``sync_*`` helpers were removed),
* tool calls flatten their parameters beside ``tool`` and proposals report
  corrections through ``correction`` instead of ``context_result``.

The affected tests are kept (they still document former behaviour and are useful
reference while porting them), but they are skipped in the default run so that a
red suite keeps meaning "the compiler regressed". Set ``ARC_LEGACY_TESTS=1`` to
run them again when porting.
"""

import os
import unittest


LEGACY_REASON = (
    "Predates the current contracts (incremental edit spans, model-owned wiring, "
    "flattened tool calls); set ARC_LEGACY_TESTS=1 to run and port it")


def legacy(test):
    """Skip a test that encodes a superseded contract unless auditing it explicitly."""
    return unittest.skipUnless(os.environ.get("ARC_LEGACY_TESTS"), LEGACY_REASON)(test)

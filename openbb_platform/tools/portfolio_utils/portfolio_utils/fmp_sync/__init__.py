"""Guarded FMP price warming for Hermes no-agent cron and manual runs (#1344, HFP-P07).

Modules:

- ``locking`` -- one non-blocking cross-process lock per target database, shared
  by the manual CLI, the openbb-jobs handler and the cron dispatcher.
- ``admission`` -- ordered target and universe admission before any DB or FMP
  access; reuses ``openbb_agents.hermes_integration`` (#1338) lazily.

Importing this package has no side effects: it does not import the warmer (whose
import loads a ``.env`` with ``override=True``) or ``openbb_agents``.
"""

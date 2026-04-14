"""Long-running background services hosted by the daemon process.

Routers in :mod:`iris.daemon.routes` handle request/response cycles; anything
that outlives a single request (filesystem watchers, embedding workers,
reflection jobs, summarizers) lives here. See
``src/iris/daemon/CLAUDE.md`` §5 for the broader plan.
"""

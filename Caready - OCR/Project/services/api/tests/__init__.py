"""API tests.

A package rather than a bare directory so `from .conftest import requires_db`
works - the database-dependent tests need to share that skip marker.
"""

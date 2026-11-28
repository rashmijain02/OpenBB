"""Hermetic fixtures for the resumable-run tests (#1341).

The parent ``hermes_integration`` conftest already moves home directories to a
temporary root and denies non-loopback network. Hermes IDs used here are
synthetic; nothing imports or runs Hermes.
"""

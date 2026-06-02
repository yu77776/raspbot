"""Canonical wire protocol — single source of truth for Car, PC, and App.

Keep changes here aligned with docs/protocol.md. Car and PC sides both
import from this module; the App (Kotlin) should reference the same token
vocabulary and field names documented here.
"""

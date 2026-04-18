"""
Pytest configuration — add myntist-beacon to sys.path.

The canonical Python package directories are:
  iam_substrate/   (was: iam-substrate/)
  beacon_core/     (was: beacon-core/)
  identity_loop/   (was: identity-loop/)

For backward compatibility the hyphenated originals still exist,
but all production imports use the underscore-named versions.
"""
import sys
import os

# Add the myntist-beacon directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

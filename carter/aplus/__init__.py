"""A+: human-run ``carter push`` and its building blocks (RFC-0007 C.6.6; D72).

The modules here are pure where they can be (they return findings and print nothing), so
the broker imports them: ``repocfg``, ``sshcfg``, ``sigcheck``, ``rangecalc``. None imports
click.
"""

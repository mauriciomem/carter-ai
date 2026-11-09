"""`carter push`: human-run ``carter push`` and its building blocks.

The modules here are pure where they can be (they return findings and print nothing), so
the broker imports them: ``repocfg``, ``sshcfg``, ``sigcheck``, ``rangecalc``. None imports
click.
"""

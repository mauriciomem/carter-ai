"""A+: human-run ``carter push`` / ``carter pr`` and their building blocks (RFC-0007 C.6.6).

The modules here are pure where they can be (they return findings and print nothing), so
slice B's broker can import them later: ``handoff``, ``secretscan``, ``repocfg``,
``sshcfg``, ``sigcheck``, ``rangecalc``. None imports click.
"""

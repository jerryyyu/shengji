"""Oracle CEILING arms for the production search policy.

Nothing in this package is a candidate policy.  The arms deliberately exceed
production compute to bound what a better leaf value (``value``) or a better
ballot prior (``prior``) could buy the registered ``mc-s0-report-lcb`` search
before any learned component is built.  Production code under ``shengji.ai``
and ``shengji.engine`` is untouched: every arm is a subclass mixed over the
registered production class.

See :mod:`shengji.oracle.screen` and ``scripts/oracle_screen.py``.
"""

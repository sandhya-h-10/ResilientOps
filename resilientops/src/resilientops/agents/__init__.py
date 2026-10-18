"""Five bounded roles; no agent has execution credentials."""

from .commander import Commander
from .impact import Impact
from .investigator import Investigator
from .recovery import Recovery
from .sentinel import Sentinel

STAGES = (Sentinel(), Investigator(), Impact(), Recovery(), Commander())

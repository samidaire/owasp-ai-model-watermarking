"""Bridge to the hardened stdlib demo server (demo/server.py), which stays the fallback until Gate 1.

The FastAPI backend reuses its step catalogue (STEPS, STEP_INFO with timeouts), its job semantics
(Job/SimJob: cancel, watchdog timeout, crash-safe run(), process-tree kill), its simulate-mode log
lookup and its Host/Origin parsers, so v1 behaves identically. demo/server.py itself is not modified.
"""
from __future__ import annotations

import importlib.util
import sys

from .config import DEMO

if str(DEMO) not in sys.path:          # demo/server.py does `from demo_common import ...`
    sys.path.append(str(DEMO))

_spec = importlib.util.spec_from_file_location("sigil_demo_server", DEMO / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

import demo_common  # noqa: E402  (importable once demo/ is on sys.path)

API_VERSION = server.API_VERSION
STEPS = server.STEPS                    # shared dict objects: tests may monkeypatch entries
STEP_INFO = server.STEP_INFO
DEFAULT_TRIES = server.DEFAULT_TRIES
TRIES_ALLOWED = server.TRIES_ALLOWED
MAX_BODY = server.MAX_BODY
CANCEL_WAIT = server.CANCEL_WAIT
CODE_CANCELLED = server.CODE_CANCELLED
CODE_TIMED_OUT = server.CODE_TIMED_OUT
LOCAL_HOSTS = server.LOCAL_HOSTS
CONTENT_TYPES = server.CONTENT_TYPES
POPEN_GROUP = server.POPEN_GROUP
SIM_LOGS = server.SIM_LOGS

Job = server.Job
SimJob = server.SimJob
host_of = server.host_of
origin_allowed = server.origin_allowed
kill_tree = server.kill_tree
rel = server.rel
read_json = server.read_json
sim_log_for = server.sim_log_for
parse_object = server.Handler.parse_object
safe_join = server.Handler.safe_join

child_env = demo_common.child_env
is_noise = demo_common.is_noise
scrub_paths = demo_common.scrub_paths
current_commitment = demo_common.current_commitment

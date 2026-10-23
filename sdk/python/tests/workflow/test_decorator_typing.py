"""Check the public workflow decorators with a static type checker."""

import os
import subprocess
import sys
from pathlib import Path

_SDK_ROOT = Path(__file__).resolve().parents[2]
_CONSUMER = """
from typing import assert_type

from pydantic import BaseModel

from jamjet import Workflow

wf = Workflow("typed")

@wf.state
class State(BaseModel):
    value: str

@wf.step
def bare_sync(state: State) -> State:
    assert_type(state.value, str)
    return state

@wf.step
async def bare_async(state: State) -> State:
    return state

@wf.step(name="configured_sync", timeout="30s")
def configured_sync(state: State, *, label: str) -> State:
    return state

@wf.step(next={"end": lambda state: True}, human_approval=True)
async def configured_async(state: State, *, limit: int = 1) -> State:
    return state

@wf.step(None, name="explicit_none")
def explicit_none(state: State) -> State:
    return state

def original(state: State, *, count: int = 1) -> State:
    return state

registered = wf.step(original, name="direct")
decorate = wf.step()
reused_sync = decorate(original)
reused_async = decorate(bare_async)

state = State(value="hello")
assert_type(state.value, str)
assert_type(bare_sync(state), State)
assert_type(configured_sync(state, label="hello"), State)
assert_type(explicit_none(state), State)
assert_type(registered(state, count=2), State)
assert_type(reused_sync(state, count=2), State)

async def check_async() -> None:
    assert_type(await bare_async(state), State)
    assert_type(await configured_async(state, limit=2), State)
    assert_type(await reused_async(state), State)
"""


def _check_consumer(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    consumer = tmp_path / "consumer.py"
    consumer.write_text(source, encoding="utf-8")
    env = os.environ.copy()
    # Resolve the checkout being tested even if another SDK version is installed.
    env["MYPYPATH"] = str(_SDK_ROOT)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(_SDK_ROOT / "pyproject.toml"),
            "--follow-imports=silent",
            "--python-version=3.12",
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / "mypy_cache"),
            str(consumer),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_workflow_decorators_preserve_types(tmp_path: Path):
    result = _check_consumer(tmp_path, _CONSUMER)
    assert result.returncode == 0, result.stdout + result.stderr


def test_workflow_steps_reject_invalid_arguments(tmp_path: Path):
    result = _check_consumer(
        tmp_path,
        _CONSUMER
        + """
bare_sync("wrong state")
configured_sync(state)
registered(state, count="wrong count")
""",
    )
    diagnostics = result.stdout + result.stderr
    assert result.returncode == 1, diagnostics
    assert diagnostics.count("[arg-type]") == 2, diagnostics
    assert diagnostics.count("[call-arg]") == 1, diagnostics
    assert "[assert-type]" not in diagnostics, diagnostics

"""Pure regression tests for the dock's queued-event run gate."""

from ui.dock import _RunUiGate


def test_gate_accepts_only_the_active_run():
    gate = _RunUiGate()
    gate.activate(7)

    assert gate.accepts(7)
    assert not gate.accepts(6)
    assert not gate.accepts(8)


def test_new_run_invalidates_queued_work_from_previous_run():
    gate = _RunUiGate()
    gate.activate(10)
    gate.activate(11)

    assert not gate.accepts(10)
    assert gate.accepts(11)


def test_invalidating_old_run_cannot_cancel_newer_gate():
    gate = _RunUiGate()
    gate.activate(20)
    gate.activate(21)

    gate.invalidate(20)

    assert gate.accepts(21)


def test_invalidating_active_run_rejects_delayed_callbacks():
    gate = _RunUiGate()
    gate.activate(30)
    gate.invalidate(30)

    assert not gate.accepts(30)

import pytest

from codexdeck_core import ErrorCode, RunState, StateMachine, StateTransitionError


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (RunState.IDLE, RunState.STARTING),
        (RunState.STARTING, RunState.RUNNING),
        (RunState.STARTING, RunState.ERROR),
        (RunState.RUNNING, RunState.STOPPING),
        (RunState.RUNNING, RunState.ERROR),
        (RunState.STOPPING, RunState.IDLE),
        (RunState.STOPPING, RunState.ERROR),
        (RunState.ERROR, RunState.IDLE),
        (RunState.ERROR, RunState.STARTING),
    ],
)
def test_state_machine_allows_legal_transitions(current: RunState, next_state: RunState) -> None:
    machine = StateMachine(state=current)

    assert machine.transition_to(next_state) is next_state
    assert machine.state is next_state


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (RunState.IDLE, RunState.RUNNING),
        (RunState.RUNNING, RunState.RUNNING),
        (RunState.STOPPING, RunState.RUNNING),
        (RunState.ERROR, RunState.STOPPING),
    ],
)
def test_state_machine_rejects_illegal_transitions(current: RunState, next_state: RunState) -> None:
    machine = StateMachine(state=current)

    with pytest.raises(StateTransitionError) as exc_info:
        machine.transition_to(next_state)

    assert exc_info.value.error_code is ErrorCode.INVALID_TRANSITION
    assert machine.state is current

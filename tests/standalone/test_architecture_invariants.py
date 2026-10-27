"""Static checks for architecture rules that review found broken once."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]

# Transport commands that stop playback share one implementation.
STOP_COMMANDS = ("pause", "stop")
STOP_IMPLEMENTATION = "_stop_playback"


def _parse(name: str) -> ast.Module:
    return ast.parse((PROJECT_ROOT / "provider" / name).read_text(encoding="utf-8"))


def _player_method(name: str) -> ast.AsyncFunctionDef:
    module = _parse("player.py")
    player = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "YandexStationPlayer"
    )
    return next(
        node for node in player.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def test_provider_leaves_player_authorization_to_the_core() -> None:
    """
    The provider never reads a user's player_filter.

    Whether a user may use a player depends on more than that filter (full-access
    users ignore it, a client may use its own player). A local copy of the rule
    drifts from the core's; ask the core instead (players.get_player_state).
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted((PROJECT_ROOT / "provider").glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "player_filter"
    ]
    assert offenders == []


def test_pause_and_stop_share_one_implementation() -> None:
    """
    pause() and stop() only await _stop_playback.

    Both lead to the same Station state while the command is pending; separate
    copies drifted once (only pause guarded against stale playing reports).
    """
    for name in STOP_COMMANDS:
        method = _player_method(name)
        awaited = [
            node.value.func
            for node in ast.walk(method)
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
        ]
        assert [func.attr for func in awaited if isinstance(func, ast.Attribute)] == [
            STOP_IMPLEMENTATION
        ], name
        assert not any(
            isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            for node in ast.walk(method)
        ), name


def test_transport_commands_set_state_before_awaiting_the_station() -> None:
    """
    The stop implementation assigns no player state after its first await.

    Glagol dispatches the state carried by a command's response frame before send()
    returns, so state assigned after the await misses that update.
    """
    offenders: list[str] = []
    for name in (STOP_IMPLEMENTATION,):
        awaited = False
        for statement in _player_method(name).body:
            if awaited:
                offenders.extend(
                    f"{name}:{node.lineno}"
                    for node in ast.walk(statement)
                    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    and any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        for target in (
                            node.targets if isinstance(node, ast.Assign) else [node.target]
                        )
                    )
                )
            if any(isinstance(node, ast.Await) for node in ast.walk(statement)):
                awaited = True
    assert offenders == []


def test_station_reports_go_through_the_epoch_counter() -> None:
    """
    Only _update_playback_state applies a Station report.

    It counts reports that change the session, which decides whether a failed
    transport command may restore the session it replaced. Applying a report
    elsewhere would skip that count.
    """
    callers = [
        f"{path.name}:{node.lineno}"
        for path in sorted((PROJECT_ROOT / "provider").glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "_apply_playback_report"
    ]
    assert len(callers) == 1


def test_stop_implementation_rolls_back_when_cancelled() -> None:
    """
    Every await in the stop implementation is covered by a CancelledError handler.

    The command's state is applied before the await; a cancelled send would
    otherwise leave the Music Assistant session cleared and stale playing reports
    ignored until the Station happens to report a stop.
    """

    def handles_cancellation(node: ast.Try) -> bool:
        return any(
            isinstance(handler.type, ast.Attribute) and handler.type.attr == "CancelledError"
            for handler in node.handlers
        )

    method = _player_method(STOP_IMPLEMENTATION)
    covered = {
        id(inner)
        for node in ast.walk(method)
        if isinstance(node, ast.Try) and handles_cancellation(node)
        for statement in node.body
        for inner in ast.walk(statement)
    }
    uncovered = [
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Await) and id(node) not in covered
    ]
    assert uncovered == []

"""Static checks for architecture rules that review found broken once."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]

# Transport commands record the state they lead to before awaiting the Station.
TRANSPORT_COMMANDS = ("pause", "stop")


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


def test_transport_commands_set_state_before_awaiting_the_station() -> None:
    """
    pause() and stop() assign no player state after their first await.

    Glagol dispatches the state carried by a command's response frame before send()
    returns, so state assigned after the await misses that update.
    """
    offenders: list[str] = []
    for name in TRANSPORT_COMMANDS:
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

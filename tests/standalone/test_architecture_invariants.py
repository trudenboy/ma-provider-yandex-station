"""Static checks for architecture rules that review found broken once."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]

TRANSPORT_COMMANDS = ("play", "pause", "stop")
# Queue operations the core owns; the player reports state and the core decides.
QUEUE_CONTROL = frozenset({"resume", "pause", "stop", "play", "next", "previous", "play_index"})
# The request token that drops a superseded play_media(); not player state.
REQUEST_TOKEN = "_external_play_generation"
# Helpers that change the reported session.
SESSION_HELPERS = frozenset({"_start_external_session", "_end_external_session"})
ALICE_STATE_VALUES = frozenset({"LISTENING", "BUSY", "SPEAKING", "NONE"})


def _modules() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted((PROJECT_ROOT / "provider").glob("*.py"))
    ]


def _player_method(name: str) -> ast.AsyncFunctionDef:
    module = ast.parse((PROJECT_ROOT / "provider" / "player.py").read_text(encoding="utf-8"))
    player = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "YandexStationPlayer"
    )
    return next(
        node for node in player.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _self_attribute(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def test_provider_leaves_player_authorization_to_the_core() -> None:
    """
    The provider never reads a user's player_filter.

    Whether a user may use a player depends on more than that filter (full-access
    users ignore it, a client may use its own player). A local copy of the rule
    drifts from the core's; ask the core instead (players.get_player_state).
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, module in _modules()
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute) and node.attr == "player_filter"
    ]
    assert offenders == []


def test_provider_leaves_queue_control_to_the_core() -> None:
    """
    The provider never resumes, pauses or steps a queue itself.

    The core decides what play means for a player: it resumes the queue of a
    player that is not paused, and stops a stream the player cannot pause. A
    provider that drives the queue on its own races the core's decisions
    (music-assistant/server#2283). Ask the player controller instead.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, module in _modules()
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        and node.attr in QUEUE_CONTROL
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "player_queues"
    ]
    assert offenders == []


def test_transport_commands_change_no_state_before_the_station_accepts() -> None:
    """
    play(), pause() and stop() change no reported state before their first await.

    The Station's reports decide the state; a command only records what the
    Station confirmed. A command that is rejected or cancelled then leaves
    nothing behind to roll back.
    """
    offenders: list[str] = []
    for name in TRANSPORT_COMMANDS:
        for statement in _player_method(name).body:
            if any(isinstance(node, ast.Await) for node in ast.walk(statement)):
                break
            for node in ast.walk(statement):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    attr = _self_attribute(target)
                    if attr and attr != REQUEST_TOKEN and attr.startswith(("_attr_", "_external_")):
                        offenders.append(f"{name}:{target.lineno}")
                if isinstance(node, ast.Call) and _self_attribute(node.func) in SESSION_HELPERS:
                    offenders.append(f"{name}:{node.func.lineno}")
    assert offenders == []


def test_alice_states_are_interpreted_only_by_the_tracker() -> None:
    """
    Only alice.py reads aliceState values.

    The same values mean different things in context (NONE is Alice's answer
    inside a request but a server-action phrase on its own); separate readings
    drifted apart several times. Consumers use AliceTracker's activity.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, module in _modules()
        if path.name != "alice.py"
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and node.value in ALICE_STATE_VALUES
    ]
    assert offenders == []


def test_player_schedules_work_through_the_core() -> None:
    """
    The player starts no bare asyncio tasks.

    The core's scheduler (mass.create_task, mass.call_later with a task_id)
    keeps a reference, cancels on unload and logs failures.
    """
    module = ast.parse((PROJECT_ROOT / "provider" / "player.py").read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        and node.attr == "create_task"
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    ]
    assert offenders == []


def test_stream_is_identified_by_the_reported_track_id_not_its_title() -> None:
    """
    No comparison involves a title.

    The Station reports an empty track id for a stream handed over with
    audio_play and the Yandex Music track id for its own playback. Titles are
    display data: two sources can share one, and comparing them guessed wrong.
    """

    def names_title(node: ast.AST) -> bool:
        return any(
            (isinstance(sub, ast.Attribute) and "title" in sub.attr)
            or (isinstance(sub, ast.Name) and "title" in sub.id)
            or (isinstance(sub, ast.Constant) and sub.value == "title")
            for sub in ast.walk(node)
        )

    offenders = [
        f"{path.name}:{node.lineno}"
        for path, module in _modules()
        for node in ast.walk(module)
        if isinstance(node, ast.Compare)
        and any(names_title(part) for part in (node.left, *node.comparators))
    ]
    assert offenders == []


def test_current_media_is_published_through_one_helper() -> None:
    """
    Only _publish_media calls set_current_media.

    The core's setter merges into the previous media and keeps fields it gets
    empty, so a caller that skips the helper inherits the previous item's type
    or cover after the item changed.
    """
    module = ast.parse((PROJECT_ROOT / "provider" / "player.py").read_text(encoding="utf-8"))
    player = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "YandexStationPlayer"
    )
    offenders = [
        f"{method.name}:{node.lineno}"
        for method in player.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        and method.name != "_publish_media"
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and _self_attribute(node.func) == "set_current_media"
    ]
    assert offenders == []

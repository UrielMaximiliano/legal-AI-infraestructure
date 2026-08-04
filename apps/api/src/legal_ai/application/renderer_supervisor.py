"""Spawn-isolated renderer execution with deterministic termination."""

from __future__ import annotations

import multiprocessing
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Protocol

from legal_ai.domain.errors import (
    GenerationTimeoutError,
    RendererExecutionError,
)


class ChildRenderer(Protocol):
    def render(self, input_data: Any, output_path: Path) -> None: ...


@dataclass(frozen=True)
class RendererSupervisor:
    """Run exactly one renderer operation in one disposable child process."""

    grace_seconds: float = 0.5
    process_factory: Any | None = None
    context: Any | None = None

    def run(
        self,
        renderer: ChildRenderer,
        input_data: Any,
        output_path: Path,
        timeout_seconds: int,
    ) -> Path:
        if timeout_seconds <= 0:
            raise RendererExecutionError()
        context = self.context or multiprocessing.get_context("spawn")
        factory = self.process_factory or context.Process
        parent, child = context.Pipe(duplex=False)
        process: Any | None = None
        completed = False
        try:
            process = factory(
                target=_render_child,
                args=(renderer, input_data, output_path, child),
            )
            process.start()
            child.close()
            process.join(timeout_seconds)
            if process.is_alive():
                process.terminate()
                process.join(self.grace_seconds)
                if process.is_alive():
                    process.kill()
                process.join()
                raise GenerationTimeoutError()
            process.join()
            if process.exitcode not in (0, None):
                raise RendererExecutionError()
            if not parent.poll():
                raise RendererExecutionError()
            message = parent.recv()
            if not isinstance(message, dict) or not message.get("ok"):
                raise RendererExecutionError()
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise RendererExecutionError()
            completed = True
            return output_path
        except GenerationTimeoutError:
            raise
        except (OSError, EOFError, ValueError, TypeError) as exc:
            raise RendererExecutionError() from exc
        finally:
            with suppress(OSError, AttributeError):
                parent.close()
            if process is not None and process.is_alive():
                process.terminate()
                process.join()
            if not completed:
                _remove_output(output_path)


def _render_child(
    renderer: ChildRenderer,
    input_data: Any,
    output_path: Path,
    connection: Connection,
) -> None:
    """Child entry point: only serializable data crosses the process boundary."""
    try:
        renderer.render(input_data, output_path)
        connection.send({"ok": True})
    except Exception:
        connection.send({"ok": False})
    finally:
        connection.close()


def _remove_output(output_path: Path) -> None:
    try:
        if output_path.is_file() or output_path.is_symlink():
            output_path.unlink()
    except OSError:
        pass

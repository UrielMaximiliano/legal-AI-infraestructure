"""Single-slot, bounded and priority-aware inference coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

from legal_ai.ports.embedding import InferenceCoordinationPort, InferencePriority

T = TypeVar("T")


@dataclass(order=True)
class _WorkItem:
    priority: int
    sequence: int
    operation: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)


class InferenceCoordinator(InferenceCoordinationPort):
    """Runs at most one Ollama call and keeps database work outside the slot."""

    def __init__(
        self,
        *,
        max_queue_size: int = 32,
        wait_timeout: float = 30.0,
        shutdown_timeout: float = 30.0,
    ) -> None:
        if max_queue_size <= 0 or wait_timeout <= 0 or shutdown_timeout <= 0:
            raise ValueError("INFERENCE_COORDINATOR_LIMIT_INVALID")
        self._queue: asyncio.PriorityQueue[_WorkItem] = asyncio.PriorityQueue(
            maxsize=max_queue_size
        )
        self._wait_timeout = wait_timeout
        self._shutdown_timeout = shutdown_timeout
        self._sequence = 0
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._fully_closed = False
        self._active = False
        self._consecutive_interactive = 0
        self._lifecycle_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._producers: set[asyncio.Task[Any]] = set()

    async def _next_item(self) -> _WorkItem:
        """Prefer priority, but periodically release a waiting lower class."""
        first = await self._queue.get()
        if self._consecutive_interactive < 3 or self._queue.empty():
            return first
        candidates = [first]
        while True:
            try:
                candidates.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        chosen = max(candidates, key=lambda item: item.priority)
        for item in candidates:
            if item is not chosen:
                self._queue.put_nowait(item)
        self._consecutive_interactive = 0
        return chosen

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run_worker())

    async def _run_worker(self) -> None:
        while not self._closed:
            item = await self._next_item()
            try:
                if item.future.cancelled():
                    continue
                try:
                    self._active = True
                    result: Any = await item.operation()
                except asyncio.CancelledError:
                    if not item.future.done():
                        item.future.cancel()
                    raise
                except Exception as exc:  # noqa: BLE001 - propagate provider error
                    if not item.future.done():
                        item.future.set_exception(exc)
                else:
                    if not item.future.done():
                        item.future.set_result(result)
                finally:
                    self._active = False
            finally:
                if item.priority < int(InferencePriority.BATCH_INGESTION):
                    self._consecutive_interactive += 1
                else:
                    self._consecutive_interactive = 0
                self._queue.task_done()

    async def execute(
        self,
        priority: InferencePriority,
        operation: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
    ) -> T:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        producer = asyncio.current_task()
        if producer is None:  # pragma: no cover - asyncio always supplies one here
            raise RuntimeError("INFERENCE_COORDINATOR_TASK_REQUIRED")
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("INFERENCE_COORDINATOR_CLOSED")
            self._ensure_worker()
            item = _WorkItem(
                int(priority),
                self._sequence,
                cast("Callable[[], Awaitable[Any]]", operation),
                cast("asyncio.Future[Any]", future),
            )
            self._sequence += 1
            self._producers.add(producer)
        try:
            await asyncio.wait_for(
                self._queue.put(item), timeout=timeout or self._wait_timeout
            )
        except asyncio.CancelledError:
            future.cancel()
            raise
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("INFERENCE_TIMEOUT") from exc
        finally:
            async with self._lifecycle_lock:
                self._producers.discard(producer)
        try:
            result = await asyncio.wait_for(
                future, timeout=timeout or self._wait_timeout
            )
            return result
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("INFERENCE_TIMEOUT") from exc

    def _cancel_queued(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if not item.future.done():
                item.future.cancel()
            self._queue.task_done()

    async def close(self, *, shutdown_timeout: float | None = None) -> None:
        """Stop intake, cancel queued work and await active inference safely."""
        timeout = (
            shutdown_timeout if shutdown_timeout is not None else self._shutdown_timeout
        )
        if timeout <= 0:
            raise ValueError("INFERENCE_SHUTDOWN_TIMEOUT_INVALID")
        async with self._close_lock:
            if self._fully_closed:
                return
            async with self._lifecycle_lock:
                self._closed = True
                producers = tuple(self._producers)

            # A producer is registered before it can wait for queue capacity.
            # Waiting for every registered producer to stop before the final drain
            # makes insertion-after-drain impossible.
            for producer in producers:
                producer.cancel()
            if producers:
                await asyncio.gather(*producers, return_exceptions=True)

            self._cancel_queued()
            if self._worker is not None:
                if self._active:
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(self._worker), timeout=timeout
                        )
                    except TimeoutError as exc:
                        raise RuntimeError("INFERENCE_SHUTDOWN_TIMEOUT") from exc
                else:
                    self._worker.cancel()
                    await asyncio.gather(self._worker, return_exceptions=True)
                if self._worker.done():
                    self._worker = None
            self._cancel_queued()
            self._fully_closed = True

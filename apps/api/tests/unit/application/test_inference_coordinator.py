import asyncio

import pytest

from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.ports.embedding import InferencePriority


@pytest.mark.asyncio
async def test_single_slot_and_search_priority() -> None:
    coordinator = InferenceCoordinator(max_queue_size=8)
    active = 0
    maximum = 0
    events: list[str] = []

    async def operation(name: str) -> str:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        events.append(name)
        await asyncio.sleep(0.001)
        active -= 1
        return name

    first = asyncio.create_task(
        coordinator.execute(
            InferencePriority.BATCH_INGESTION, lambda: operation("batch")
        )
    )
    await asyncio.sleep(0)
    search = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, lambda: operation("search"))
    )
    assert await first == "batch"
    assert await search == "search"
    assert maximum == 1
    assert events == ["batch", "search"]
    await coordinator.close()


@pytest.mark.asyncio
async def test_timeout_cancellation_releases_slot() -> None:
    coordinator = InferenceCoordinator(max_queue_size=2, wait_timeout=0.01)

    async def slow() -> None:
        await asyncio.sleep(0.1)

    with pytest.raises(TimeoutError):
        await coordinator.execute(InferencePriority.SEARCH, slow, timeout=0.001)
    await coordinator.close()


@pytest.mark.asyncio
async def test_fairness_releases_waiting_batch_after_interactive_burst() -> None:
    coordinator = InferenceCoordinator(max_queue_size=8)
    events: list[str] = []

    async def record(name: str) -> str:
        events.append(name)
        return name

    first = [
        asyncio.create_task(
            coordinator.execute(
                InferencePriority.SEARCH, lambda name=name: record(name)
            )
        )
        for name in ("search-1", "search-2", "search-3", "search-4")
    ]
    batch = asyncio.create_task(
        coordinator.execute(InferencePriority.BATCH_INGESTION, lambda: record("batch"))
    )
    await asyncio.gather(*first, batch)
    assert events.index("batch") < events.index("search-4")
    await coordinator.close()


@pytest.mark.asyncio
async def test_close_waits_for_active_and_cancels_queued_work() -> None:
    coordinator = InferenceCoordinator(max_queue_size=4, shutdown_timeout=0.1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_operation() -> str:
        started.set()
        await release.wait()
        return "done"

    active = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, active_operation)
    )
    await started.wait()
    queued = asyncio.create_task(
        coordinator.execute(
            InferencePriority.BATCH_INGESTION, lambda: active_operation()
        )
    )
    await asyncio.sleep(0)
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0.001)
    assert not closing.done()
    release.set()
    assert await active == "done"
    await closing
    with pytest.raises(asyncio.CancelledError):
        await queued


@pytest.mark.asyncio
async def test_close_timeout_does_not_cancel_active_operation() -> None:
    coordinator = InferenceCoordinator(max_queue_size=2, shutdown_timeout=0.001)
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_operation() -> str:
        started.set()
        await release.wait()
        return "done"

    active = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, active_operation)
    )
    await started.wait()
    with pytest.raises(RuntimeError, match="INFERENCE_SHUTDOWN_TIMEOUT"):
        await coordinator.close()
    assert not active.done()
    release.set()
    assert await active == "done"
    await coordinator.close(shutdown_timeout=0.1)


@pytest.mark.asyncio
async def test_close_is_atomic_with_a_producer_blocked_on_full_queue() -> None:
    coordinator = InferenceCoordinator(max_queue_size=1, shutdown_timeout=0.2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_operation() -> str:
        started.set()
        await release.wait()
        return "active"

    active = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, active_operation)
    )
    await started.wait()
    queued = asyncio.create_task(
        coordinator.execute(InferencePriority.BATCH_INGESTION, active_operation)
    )
    await asyncio.sleep(0)
    blocked = asyncio.create_task(
        coordinator.execute(InferencePriority.BATCH_INGESTION, active_operation)
    )
    await asyncio.sleep(0)

    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    release.set()
    assert await active == "active"
    await closing

    for task in (queued, blocked):
        with pytest.raises(asyncio.CancelledError):
            await task
    assert coordinator._queue.qsize() == 0
    assert coordinator._worker is None
    assert not coordinator._producers
    with pytest.raises(RuntimeError, match="INFERENCE_COORDINATOR_CLOSED"):
        await coordinator.execute(InferencePriority.SEARCH, active_operation)


@pytest.mark.asyncio
async def test_close_handles_multiple_blocked_producers_and_is_idempotent() -> None:
    coordinator = InferenceCoordinator(max_queue_size=1, shutdown_timeout=0.2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation() -> str:
        started.set()
        await release.wait()
        return "done"

    active = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, operation)
    )
    await started.wait()
    waiting = [
        asyncio.create_task(
            coordinator.execute(InferencePriority.BATCH_INGESTION, operation)
        )
        for _ in range(5)
    ]
    await asyncio.sleep(0)
    closers = [asyncio.create_task(coordinator.close()) for _ in range(2)]
    await asyncio.sleep(0)
    release.set()
    assert await active == "done"
    await asyncio.gather(*closers)
    results = await asyncio.gather(*waiting, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert coordinator._queue.qsize() == 0
    assert not coordinator._producers
    await coordinator.close()


@pytest.mark.asyncio
async def test_close_with_empty_queue_and_provider_failure_has_no_task_leak() -> None:
    empty = InferenceCoordinator(max_queue_size=1)
    await empty.close()
    assert empty._queue.qsize() == 0
    assert empty._worker is None

    coordinator = InferenceCoordinator(max_queue_size=1, shutdown_timeout=0.2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def failing_operation() -> None:
        started.set()
        await release.wait()
        raise RuntimeError("PROVIDER_FAILED")

    caller = asyncio.create_task(
        coordinator.execute(InferencePriority.SEARCH, failing_operation),
        name="coordinator-provider-failure-caller",
    )
    await started.wait()
    closing = asyncio.create_task(
        coordinator.close(), name="coordinator-provider-failure-close"
    )
    release.set()
    with pytest.raises(RuntimeError, match="PROVIDER_FAILED"):
        await caller
    await closing
    assert coordinator._queue.qsize() == 0
    assert coordinator._worker is None
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and task.get_name().startswith("coordinator-provider-failure")
        and not task.done()
    ]


@pytest.mark.asyncio
async def test_atomic_close_race_is_stable_across_repetitions() -> None:
    for _ in range(10):
        coordinator = InferenceCoordinator(max_queue_size=1, shutdown_timeout=0.2)
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation(
            started_event: asyncio.Event = started,
            release_event: asyncio.Event = release,
        ) -> None:
            started_event.set()
            await release_event.wait()

        active = asyncio.create_task(
            coordinator.execute(InferencePriority.SEARCH, operation)
        )
        await started.wait()
        waiting = [
            asyncio.create_task(
                coordinator.execute(InferencePriority.BATCH_INGESTION, operation)
            )
            for _ in range(3)
        ]
        await asyncio.sleep(0)
        closing = asyncio.create_task(coordinator.close())
        await asyncio.sleep(0)
        release.set()
        await active
        await closing
        await asyncio.gather(*waiting, return_exceptions=True)
        assert coordinator._queue.qsize() == 0
        assert coordinator._worker is None
        assert not coordinator._producers

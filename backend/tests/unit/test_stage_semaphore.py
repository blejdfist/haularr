import asyncio

import pytest
from app.jobs.scheduler import JobScheduler


async def test_lowering_download_limit_keeps_existing_holders(settings):
    scheduler = JobScheduler(settings)
    slots = scheduler._stage_semaphores["transfer"]
    assert all([await slots.acquire() for _ in range(3)])

    settings.max_concurrent_download_jobs = 2
    scheduler.update_concurrency_limits()
    assert not await slots.acquire()
    slots.release()
    assert not await slots.acquire()
    slots.release()
    assert await slots.acquire()
    assert not await slots.acquire()
    slots.release()
    slots.release()
    assert all([await slots.acquire() for _ in range(2)])
    assert not await slots.acquire()


async def test_resize_while_acquire_is_pending(settings):
    slots = JobScheduler(settings)._stage_semaphores["transfer"]
    assert all([await slots.acquire() for _ in range(3)])
    pending = asyncio.create_task(slots.acquire())
    await asyncio.sleep(0)
    slots.set_limit(4)
    assert await pending
    assert not await slots.acquire()


async def test_cancelled_waiter_does_not_consume_capacity(settings):
    slots = JobScheduler(settings)._stage_semaphores["transfer"]
    assert all([await slots.acquire() for _ in range(3)])
    pending = asyncio.create_task(slots.acquire())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    slots.release()
    assert await slots.acquire()
    assert not await slots.acquire()


async def test_waiters_share_only_available_capacity_after_resize(settings):
    slots = JobScheduler(settings)._stage_semaphores["transfer"]
    assert all([await slots.acquire() for _ in range(3)])
    waiters = [asyncio.create_task(slots.acquire()) for _ in range(3)]
    await asyncio.sleep(0)
    slots.set_limit(4)
    assert sum(await asyncio.gather(*waiters)) == 1
    assert slots.current_value == 0

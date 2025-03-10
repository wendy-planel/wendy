import json
import time
from typing import Dict

import asyncio

import httpx
from fastapi import APIRouter, Request, Query
from sse_starlette.sse import EventSourceResponse

from wendy import models
from wendy.constants import DeployStatus
from wendy.cluster import Cluster, ClusterWorld


router = APIRouter()


class Stats:
    def __init__(self, request: Request, interval: int):
        self.request = request
        self.interval = interval
        self.queue = asyncio.Queue()
        self.tasks: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()
        self._started = False
        self._task: asyncio.Task | None = None

    def __aiter__(self):
        return self

    async def _read(
        self,
        key: str,
        world: ClusterWorld,
    ):
        if world.docker_api.startswith("http"):
            transport = None
            base_url = world.docker_api.replace("unix://", "")
        else:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            base_url = "http://docker"
        try:
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                url = f"/containers/{world.container}/stats"
                timeout = httpx.Timeout(None, connect=5)
                async with client.stream("GET", url, timeout=timeout) as response:
                    start_time = time.time()
                    async for chunk in response.aiter_raw():
                        current_time = time.time()
                        elapsed_time = current_time - start_time
                        if elapsed_time >= self.interval:
                            await self.queue.put(json.dumps({"key": key, "data": json.loads(chunk)}))
                            start_time = current_time
        finally:
            async with self.lock:
                if key in self.tasks:
                    self.tasks.pop(key)

    async def _watch_tasks(self):
        running = DeployStatus.running.value
        async with self.lock:
            async for deploy in models.Deploy.filter(status=running):
                cluster = Cluster.model_validate(deploy.cluster)
                for index, world in enumerate(cluster.world):
                    key = f"stats_{deploy.id}_{index}"
                    if key not in self.tasks:
                        task = asyncio.create_task(self._read(key, world))
                        self.tasks[key] = task

    async def _run(self):
        while True:
            if await self.request.is_disconnected():
                break
            else:
                await self._watch_tasks()
            await asyncio.sleep(5)
        await self.aclose()

    async def aclose(self):
        self._task.cancel()
        for _, task in self.tasks.items():
            task.cancel()

    async def __anext__(self):
        if not self._started:
            self._task = asyncio.create_task(self._run())
            self._started = True
        return await self.queue.get()

    async def __aexit__(self, _exc_type, _exc, _tb):
        await self.aclose()


@router.get("")
async def stats(request: Request, interval: int = Query()):
    return EventSourceResponse(Stats(request, interval), send_timeout=60)

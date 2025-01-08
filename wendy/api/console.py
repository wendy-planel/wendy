from typing import List

import json
import asyncio
import collections

import aiodocker
import structlog
from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Body, Query, Request

from wendy import agent, models
from wendy.cluster import Cluster, ClusterWorld


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "/command/{id}",
    description="控制台执行命令",
)
async def command(
    id: int,
    command: str = Body(),
    world_name: str = Body(),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    container_name = docker_api = None
    for world in cluster.world:
        if world.name == world_name:
            docker_api = world.docker_api
            container_name = world.container
    if docker_api is None:
        raise ValueError(f"world {world_name} not found")
    await agent.attach(command, docker_api, container_name)
    return "ok"


@router.get(
    "/logs/{id}",
    description="获取在线日志",
)
async def tail_logs(
    id: int,
    tail: int = Query(default=50),
    world_name: str = Query(),
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    container_name = docker_api = None
    for world in cluster.world:
        if world.name == world_name:
            docker_api = world.docker_api
            container_name = world.container
    if docker_api is None:
        raise ValueError(f"world {world_name} not found")
    tail += 1
    logs = collections.deque(maxlen=tail)
    async for line in agent.logs(docker_api, container_name):
        logs.append(line)
        if len(logs) == tail:
            logs.popleft()
    return logs


class LogFollow:
    def __init__(self, request: Request):
        self._started = False
        self.request = request
        self.queue = asyncio.Queue()
        self.tasks: List[asyncio.Task] = []
        self._watch_task: asyncio.Task | None = None

    def __aiter__(self):
        return self

    async def read(
        self,
        id: int,
        queue: asyncio.Queue,
        world: ClusterWorld,
    ):
        async with aiodocker.Docker(world.docker_api) as docker:
            container = await docker.containers.get(world.container)
            _iter = container.log(stdout=True, stderr=True, follow=True)
            async for data in _iter:
                message = {
                    "id": id,
                    "world_id": world.id,
                    "world_name": world.name,
                    "is_master": world.is_master,
                    "data": data,
                }
                await queue.put(json.dumps(message))

    async def _watch(self):
        while True:
            if await self.request.is_disconnected():
                break
            await asyncio.sleep(5)
        await self.aclose()

    async def aclose(self):
        for task in self.tasks:
            task.cancel()

    async def __anext__(self):
        if not self._started:
            async for deploy in models.Deploy.all():
                cluster = Cluster.model_validate(deploy.cluster)
                for world in cluster.world:
                    task = asyncio.create_task(self.read(deploy.id, self.queue, world))
                    self.tasks.append(task)
            self._started = True
            self._watch_task = asyncio.create_task(self._watch())
        return await self.queue.get()

    async def __aexit__(self, _exc_type, _exc, _tb):
        await self.aclose()


@router.get(
    "/logs",
    description="获取所有控制台日志",
)
async def sse_logs(request: Request):
    return EventSourceResponse(LogFollow(request=request), send_timeout=60)

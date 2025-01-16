from typing import Dict

import json
import asyncio

import httpx
import structlog
from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Body, Query, Request

from wendy import agent, models
from wendy.constants import DeployStatus
from wendy.cluster import Cluster, ClusterWorld


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "/{id}",
    description="控制台执行命令",
)
async def command_(
    id: int,
    command: str = Body(),
    world_index: int = Body(),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    world = cluster.world[world_index]
    docker_api = world.docker_api
    container_name = world.container
    await agent.attach(command, docker_api, container_name)
    return "ok"


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
    "/logs/tail/{id}",
    description="获取在线日志",
)
async def tail_logs(
    id: int,
    count: int = Query(),
    tail: int = Query(),
    world_index: int = Query(),
):
    data = []
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    world = cluster.world[world_index]
    if world.docker_api.startswith("http"):
        transport = None
        base_url = world.docker_api.replace("unix://", "")
    else:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        base_url = "http://docker"
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        url = f"/containers/{world.container}/logs"
        params = {
            "stdout": True,
            "stderr": True,
            "follow": False,
            "tail": tail,
        }
        line = ""
        async with client.stream("GET", url, params=params) as response:
            async for chunk in response.aiter_bytes():
                for ch in chunk.decode("utf-8"):
                    if ch == "\n":
                        if count > 0:
                            data.append(line.strip())
                            count -= 1
                        line = ""
                    else:
                        line += ch
                if count <= 0:
                    break
    return data


class LogFollow:
    def __init__(
        self,
        request: Request,
        since: int,
    ):
        self.request = request
        self.since = since
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
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url
            ) as client:
                url = f"/containers/{world.container}/logs"
                params = {
                    "stdout": True,
                    "stderr": True,
                    "follow": True,
                    "since": self.since,
                }
                line = ""
                timeout = httpx.Timeout(None, connect=5)
                async with client.stream(
                    "GET",
                    url,
                    params=params,
                    timeout=timeout,
                ) as response:
                    async for chunk in response.aiter_bytes():
                        for ch in chunk.decode("utf-8"):
                            if ch == "\n":
                                message = {"key": key, "line": line.strip()}
                                await self.queue.put(json.dumps(message))
                                line = ""
                            else:
                                line += ch
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
                    key = f"{deploy.id}_{index}"
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


@router.get("/logs/follow")
async def logs(request: Request, since: int = Query(default=0)):
    return EventSourceResponse(LogFollow(request, since), send_timeout=60)

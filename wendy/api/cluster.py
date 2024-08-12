import structlog
from fastapi import APIRouter, Query
from fastapi.responses import Response

from wendy import models, agent
from wendy.cluster import Cluster


router = APIRouter()
log = structlog.get_logger()


@router.get(
    "/download/{id}",
    description="下载存档",
)
async def download(
    id: int,
    world_name: str = Query(default="Master"),
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
    tar_file = await agent.download_archive(docker_api, container_name)
    tar_file.fileobj.seek(0)
    return Response(
        content=tar_file.fileobj.read(),
        headers={"Content-Disposition": f"attachment; filename=archive_{id}.tar"},
    )

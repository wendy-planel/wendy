import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from wendy import models, agent
from wendy.cluster import Cluster


router = APIRouter()
log = structlog.get_logger()


@router.get(
    "/download/{id}",
    description="下载存档",
)
async def download(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    docker_api = None
    for world in cluster.world:
        docker_api = world.docker_api
    tar_file = await agent.download_archive(id, docker_api)
    tar_file.fileobj.seek(0)

    # Create a generator that yields chunks from the file
    def file_chunk_generator(fileobj, chunk_size=8192):
        while chunk := fileobj.read(chunk_size):
            yield chunk

    return StreamingResponse(
        file_chunk_generator(tar_file.fileobj),
        media_type="application/x-tar",
        headers={"Content-Disposition": f"attachment; filename=archive_{id}.tar"},
    )

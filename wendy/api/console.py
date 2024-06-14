import structlog
from fastapi import APIRouter, Body

from wendy import agent, models
from wendy.cluster import Cluster


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "/command/{id}",
    description="控制台执行命令",
)
async def command(
    id: int,
    command: str = Body(..., embed=True),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.attach(command, cluster)
    return "ok"

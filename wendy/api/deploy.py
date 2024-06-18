import structlog
from fastapi import APIRouter, Body
from tortoise.transactions import atomic

from wendy.cluster import Cluster
from wendy.constants import DeployStatus
from wendy import models, agent, steamcmd


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "",
    description="部署并启动",
)
@atomic(connection_name="default")
async def create(
    cluster_token: str = Body(),
    cluster_name: str = Body(),
    cluster_description: str = Body(),
    vote_enabled: bool = Body(default=False),
):
    # 获取部署版本号
    version = await steamcmd.dst_version()
    deploy = await models.Deploy.create(
        content={},
        status=DeployStatus.pending,
    )
    # 根据ID生成7个端口号
    ports = [(10000 + deploy.id * 7 + i) for i in range(7)]
    id = str(deploy.id)
    cluster = Cluster.create_from_default(
        id=id,
        ports=ports,
        version=version,
        cluster_token=cluster_token,
        cluster_name=cluster_name,
        cluster_description=cluster_description,
        vote_enabled=vote_enabled,
    )
    # 保存游戏存档
    cluster_path = agent.get_cluster_path(id)
    cluster.save(cluster_path)
    await agent.deploy(cluster)
    # 更新状态
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running
    await deploy.save()
    return deploy


@router.get(
    "",
    description="获取所有部署",
)
async def reads():
    return await models.Deploy.all()


@router.delete(
    "/{id}",
    description="删除部署",
)
async def remove(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.delete(cluster)
    return await models.Deploy.filter(id=id).delete()


@router.get(
    "/stop/{id}",
    description="停止",
)
async def stop(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.stop(cluster)
    return await models.Deploy.filter(id=id).update(status=DeployStatus.stop)


@router.get(
    "/restart/{id}",
    description="重启",
)
async def restart(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.deploy(cluster)
    return "ok"

from fastapi import APIRouter

from wendy.api import deploy, cluster, console, mod


router = APIRouter()


@router.get("/health", description="健康检查", tags=["探针"])
async def health():
    return True


router.include_router(
    deploy.router,
    prefix="/deploy",
    tags=["部署"],
)

router.include_router(
    cluster.router,
    prefix="/cluster",
    tags=["存档"],
)

router.include_router(
    console.router,
    prefix="/console",
    tags=["控制台"],
)

router.include_router(
    mod.router,
    prefix="/mod",
    tags=["模组"],
)

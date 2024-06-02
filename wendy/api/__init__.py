from fastapi import APIRouter

from wendy.api import deploy


router = APIRouter()


@router.get("/health", description="健康检查", tags=["探针"])
async def health():
    return True


router.include_router(
    deploy.router,
    prefix="/deploy",
    tags=["部署"],
)

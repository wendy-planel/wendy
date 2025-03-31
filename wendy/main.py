"""服务入口"""

import asyncio

from contextlib import asynccontextmanager

from aerich import Command
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import register_tortoise

from wendy import agent
from wendy.api import router
from wendy.settings import APP_NAME, TORTOISE_ORM, DEBUG


@asynccontextmanager
async def lifespan(app: FastAPI):
    command = Command(
        tortoise_config=TORTOISE_ORM,
        app=APP_NAME,
        location="./migrations",
    )
    await command.init()
    await command.upgrade(run_in_transaction=True)
    register_tortoise(
        app,
        config=TORTOISE_ORM,
        add_exception_handlers=False,
    )
    if not DEBUG:
        asyncio.create_task(agent.monitor())
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)
if DEBUG:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=8000)

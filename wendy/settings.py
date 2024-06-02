import os

APP_NAME = "wendy"
DOCKER_VOLUME = os.environ.get("DOCKER_VOLUME")
DOCKERFILE_PATH = os.environ.get("DOCKERFILE_PATH")
DOCKER_URL = os.environ.get("DOCKER_URL", "unix:///var/run/docker.sock")


# 数据量配置
DATABASE_URL = os.environ.get("DATABASE_URL", default="sqlite://wendy.sqlite3")
TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        APP_NAME: {
            "models": ["wendy.models", "aerich.models"],
            "default_connection": "default",
        },
    },
    "timezone": "Asia/Shanghai",
}

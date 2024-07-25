import os

APP_NAME = "wendy"
GAME_ARCHIVE_PATH = os.environ.get("GAME_ARCHIVE_PATH")
GAME_ARCHIVE_VOLUME = os.environ.get("GAME_ARCHIVE_VOLUME", default="wendy_dst_volume")
DOCKER_URL_DEFAULT_DEFAULT = os.environ.get(
    "DOCKER_URL_DEFAULT", "unix:///var/run/docker.sock"
)
DST_IMAGE = os.environ.get("DST_IMAGE", default="ylei2023/dontstarvetogether")

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

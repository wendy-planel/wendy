FROM superjump22/dontstarvetogether:latest

# Build Arguments
ARG LANG=C.UTF-8
ARG LC_ALL=C.UTF-8
ARG DST_BRANCH

# Environment settings
ENV SteamAppId=322330
ENV SteamGameId=322330
ENV DST_DIR=${HOMEDIR}/dst
ENV DST_GAME_DIR=${DST_DIR}/game
ENV DST_SAVE_DIR=${DST_DIR}/save
ENV DST_MOD_DIR=${DST_GAME_DIR}/mods
ENV DST_UGC_MOD_DIR=${DST_GAME_DIR}/ugc_mods


RUN set -x && \
    # Install Don't Starve Together, execute as user
    su "${USER}" -c 'mkdir -p "${DST_DIR}" "${DST_GAME_DIR}" "${DST_SAVE_DIR}" "${DST_UGC_MOD_DIR}"' && \
    su "${USER}" -c  '${STEAMCMDDIR}/steamcmd.sh +force_install_dir ${DST_GAME_DIR} +login anonymous +app_update 343050 -beta "${DST_BRANCH}" validate +quit'

# Set the working directory
WORKDIR ${DST_GAME_DIR}/bin64

# Specify the entrypoint
ENTRYPOINT ["./dontstarve_dedicated_server_nullrenderer_x64"]
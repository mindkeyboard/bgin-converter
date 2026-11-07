ARG NODE_IMAGE
FROM ${NODE_IMAGE}

RUN if [ -f /etc/alpine-release ]; then \
      apk add --no-cache python3 python3-dev build-base binutils ccache; \
    else \
      apt-get update && apt-get install -y --no-install-recommends \
        python3-venv python3-dev g++ gcc patchelf binutils ccache \
        zlib1g-dev libjpeg-dev libfreetype6-dev; \
    fi

WORKDIR /workspace/bgin-converter

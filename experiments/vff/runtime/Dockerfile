FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bubblewrap \
        python3 \
        python3-pip \
        ca-certificates \
        bash \
        coreutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

CMD ["bash"]

FROM public.ecr.aws/lts/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates fuse \
      python3 python3-pip python3-venv \
      util-linux \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# Install mountpoint-s3 (arch-aware for x86_64 / arm64 hosts).
RUN ARCH=$(uname -m) \
 && case "$ARCH" in \
      x86_64)  MS_ARCH=x86_64 ;; \
      aarch64) MS_ARCH=arm64  ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/mount-s3.deb "https://s3.amazonaws.com/mountpoint-s3-release/latest/${MS_ARCH}/mount-s3.deb" \
 && dpkg -i /tmp/mount-s3.deb \
 && rm /tmp/mount-s3.deb

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]

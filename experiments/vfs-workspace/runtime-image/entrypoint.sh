#!/bin/sh
set -e

: "${S3_BUCKET:?S3_BUCKET env var required}"
: "${S3_PREFIX:?S3_PREFIX env var required}"

MOUNT_DIR="${MOUNT_DIR:-/workspace}"
mkdir -p "$MOUNT_DIR"

# --foreground keeps mount-s3 alive; run it as a background process so
# PID 1 can serve `docker exec` calls after mount comes up.
mount-s3 \
  "$S3_BUCKET" "$MOUNT_DIR" \
  --prefix "${S3_PREFIX%/}/" \
  --metadata-ttl 0 \
  --allow-delete \
  --allow-overwrite \
  --foreground &

MOUNT_PID=$!

# Wait up to 15s for the mount to become live.
i=0
while [ $i -lt 30 ]; do
  if mountpoint -q "$MOUNT_DIR"; then
    break
  fi
  i=$((i + 1))
  sleep 0.5
done

if ! mountpoint -q "$MOUNT_DIR"; then
  echo "mount-s3 failed to mount $MOUNT_DIR" >&2
  exit 1
fi

# Clean unmount on container stop.
cleanup() {
  fusermount -u "$MOUNT_DIR" 2>/dev/null || umount "$MOUNT_DIR" 2>/dev/null || true
  kill "$MOUNT_PID" 2>/dev/null || true
  wait "$MOUNT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec "$@"

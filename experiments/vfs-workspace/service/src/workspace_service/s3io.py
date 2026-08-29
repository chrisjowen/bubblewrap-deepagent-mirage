"""Direct S3 IO for workspace file browsing.

File ops (read / write / delete / ls / tree) don't need a runtime — they
just touch S3 objects under the user's prefix. This bypasses Mirage and
its associated runtime requirement so file browsing works without an
open session.

Sessions exist only for `execute` — one runtime container per session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class Entry:
    path: str            # virtual path, no bucket/prefix, leading /
    is_dir: bool
    size: int | None


class S3IO:
    def __init__(self, bucket: str, region: str, prefix: str) -> None:
        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region)
        self._prefix = prefix.strip("/")  # never leading/trailing slash

    def _key(self, virtual: str) -> str:
        v = virtual.lstrip("/")
        return f"{self._prefix}/{v}" if self._prefix else v

    def _virtual(self, key: str) -> str:
        if self._prefix and key.startswith(f"{self._prefix}/"):
            return "/" + key[len(self._prefix) + 1:]
        if key == self._prefix:
            return "/"
        return "/" + key

    def read(self, path: str) -> tuple[bytes | None, str | None]:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._key(path))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                return None, "not found"
            return None, str(exc)
        return resp["Body"].read(), None

    def write(self, path: str, data: bytes) -> str | None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=self._key(path), Body=data)
        except ClientError as exc:
            return str(exc)
        return None

    def delete(self, path: str) -> str | None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._key(path))
        except ClientError as exc:
            return str(exc)
        return None

    def ls(self, path: str = "/") -> Iterator[Entry]:
        prefix = self._key(path).rstrip("/")
        # Trailing / for "list under this dir"; empty for root of prefix.
        list_prefix = f"{prefix}/" if prefix else ""
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self._bucket, Prefix=list_prefix, Delimiter="/"
        ):
            for cp in page.get("CommonPrefixes", []) or []:
                key = cp["Prefix"].rstrip("/")
                yield Entry(path=self._virtual(key) + "/", is_dir=True, size=None)
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                # Skip the pseudo "directory" marker at the exact prefix.
                if key == list_prefix.rstrip("/"):
                    continue
                yield Entry(
                    path=self._virtual(key),
                    is_dir=False,
                    size=int(obj.get("Size", 0)),
                )

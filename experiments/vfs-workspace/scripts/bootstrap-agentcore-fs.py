"""Bootstrap AWS resources for AgentCore CodeInterpreter with S3 Files mount.

Creates (or reuses if named args match):
  1. IAM execution role with s3files + agent-core permissions
  2. S3 Files file system, mount target in the given subnet, access point
     rooted at the S3 bucket prefix
  3. AgentCore custom code interpreter with networkMode=VPC and
     filesystemConfigurations pointing at the S3 Files access point

Prints yaml snippet to paste into service/workspaces.yaml under
runtimes.code-interpreter.

Prereqs (you must supply these — the script won't create them):
  --vpc-id       existing VPC id
  --subnet-ids   comma-sep subnet ids inside the VPC (2+ AZs recommended)
  --security-group-id   SG allowing TCP 2049 outbound (mount target SG must allow inbound)
  --s3-bucket    the S3 bucket S3 Files should mount

Usage:
  uv run python scripts/bootstrap-agentcore-fs.py \\
      --name chris-vfs \\
      --region us-east-1 \\
      --vpc-id vpc-xxxxxxxx \\
      --subnet-ids subnet-aaaa,subnet-bbbb \\
      --security-group-id sg-xxxxxxxx \\
      --s3-bucket mirage-test-chris \\
      --s3-prefix chris \\
      --mount-path /mnt/s3data
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError


TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def _s3files_policy(fs_arn: str, ap_arn: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3files:ClientMount",
                    "s3files:ClientWrite",
                    "s3files:GetAccessPoint",
                ],
                "Resource": fs_arn,
                "Condition": {"ArnEquals": {"s3files:AccessPointArn": ap_arn}},
            }
        ],
    }


def ensure_role(iam, name: str) -> str:
    try:
        r = iam.get_role(RoleName=name)
        return r["Role"]["Arn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
    r = iam.create_role(
        RoleName=name,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Description="AgentCore CodeInterpreter execution role with S3 Files access",
    )
    return r["Role"]["Arn"]


def attach_s3files_policy(iam, role_name: str, policy_name: str, fs_arn: str, ap_arn: str) -> None:
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps(_s3files_policy(fs_arn, ap_arn)),
    )


def ensure_s3files_fs(s3files, name: str, bucket: str, region: str) -> str:
    for page in s3files.get_paginator("list_file_systems").paginate():
        for fs in page.get("FileSystems", []) or []:
            if fs.get("Name") == name:
                return fs["FileSystemArn"]
    r = s3files.create_file_system(
        Name=name,
        BackingStorage={"S3": {"BucketName": bucket}},
    )
    fs_id = r["FileSystemId"]
    _wait(lambda: _fs_ready(s3files, fs_id), "S3 Files fs available", 600)
    return r["FileSystemArn"]


def ensure_mount_target(s3files, fs_id: str, subnet_id: str, sg_id: str) -> str:
    for mt in s3files.describe_mount_targets(FileSystemId=fs_id).get("MountTargets", []) or []:
        if mt["SubnetId"] == subnet_id:
            return mt["MountTargetId"]
    r = s3files.create_mount_target(
        FileSystemId=fs_id, SubnetId=subnet_id, SecurityGroups=[sg_id],
    )
    mt_id = r["MountTargetId"]
    _wait(lambda: _mt_ready(s3files, mt_id), "mount target available", 600)
    return mt_id


def ensure_access_point(s3files, fs_id: str, name: str, prefix: str) -> str:
    for page in s3files.get_paginator("list_access_points").paginate(FileSystemId=fs_id):
        for ap in page.get("AccessPoints", []) or []:
            if ap.get("Name") == name:
                return ap["AccessPointArn"]
    r = s3files.create_access_point(
        FileSystemId=fs_id,
        Name=name,
        PosixUser={"Uid": 1000, "Gid": 1000},
        RootDirectory={
            "Path": f"/{prefix.strip('/')}" if prefix else "/",
            "CreationInfo": {"OwnerUid": 1000, "OwnerGid": 1000, "Permissions": "755"},
        },
    )
    return r["AccessPointArn"]


def ensure_code_interpreter(
    cp, name: str, role_arn: str, subnet_ids: list[str], sg_id: str,
    fs_arn: str, ap_arn: str, mount_path: str,
) -> tuple[str, str]:
    for page in cp.get_paginator("list_code_interpreters").paginate():
        for ci in page.get("codeInterpreterSummaries", []) or []:
            if ci.get("name") == name:
                arn = ci.get("codeInterpreterArn") or ci.get("codeInterpreterId")
                return name, arn
    r = cp.create_code_interpreter(
        name=name,
        executionRoleArn=role_arn,
        networkConfiguration={
            "networkMode": "VPC",
            "vpcConfig": {"subnets": subnet_ids, "securityGroups": [sg_id]},
        },
        filesystemConfigurations=[{
            "s3FilesConfiguration": {
                "accessPointArn": ap_arn,
                "fileSystemArn": fs_arn,
                "mountPath": mount_path,
            }
        }],
    )
    identifier = r.get("codeInterpreterArn") or r.get("codeInterpreterId") or name
    return name, identifier


def _wait(check, what: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(3)
    raise TimeoutError(f"timed out waiting for {what}")


def _fs_ready(s3files, fs_id: str) -> bool:
    try:
        r = s3files.describe_file_systems(FileSystemId=fs_id)
        return (r["FileSystems"][0].get("LifeCycleState") or "").lower() == "available"
    except ClientError:
        return False


def _mt_ready(s3files, mt_id: str) -> bool:
    try:
        r = s3files.describe_mount_targets(MountTargetId=mt_id)
        return (r["MountTargets"][0].get("LifeCycleState") or "").lower() == "available"
    except ClientError:
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True, help="prefix for created AWS resources")
    p.add_argument("--region", required=True)
    p.add_argument("--vpc-id", required=True)
    p.add_argument("--subnet-ids", required=True, help="comma-separated")
    p.add_argument("--security-group-id", required=True)
    p.add_argument("--s3-bucket", required=True)
    p.add_argument("--s3-prefix", default="")
    p.add_argument("--mount-path", default="/mnt/s3data")
    args = p.parse_args()

    subnet_ids = [s.strip() for s in args.subnet_ids.split(",") if s.strip()]

    iam = boto3.client("iam")
    s3files = boto3.client("s3files", region_name=args.region)
    cp = boto3.client("bedrock-agentcore-control", region_name=args.region)

    print(f"[1/5] IAM role {args.name}-role", flush=True)
    role_arn = ensure_role(iam, f"{args.name}-role")

    print(f"[2/5] S3 Files fs {args.name}-fs (bucket={args.s3_bucket})", flush=True)
    fs_arn = ensure_s3files_fs(s3files, f"{args.name}-fs", args.s3_bucket, args.region)
    fs_id = fs_arn.split("/")[-1]

    print(f"[3/5] mount targets in {len(subnet_ids)} subnets", flush=True)
    for sn in subnet_ids:
        ensure_mount_target(s3files, fs_id, sn, args.security_group_id)

    print(f"[4/5] access point {args.name}-ap (root=/{args.s3_prefix.strip('/')})", flush=True)
    ap_arn = ensure_access_point(s3files, fs_id, f"{args.name}-ap", args.s3_prefix)
    attach_s3files_policy(iam, f"{args.name}-role", f"{args.name}-s3files", fs_arn, ap_arn)

    print(f"[5/5] code interpreter {args.name}-ci (VPC + mount)", flush=True)
    ci_name, ci_id = ensure_code_interpreter(
        cp, f"{args.name}-ci", role_arn, subnet_ids, args.security_group_id,
        fs_arn, ap_arn, args.mount_path,
    )

    print("\n=== paste into service/workspaces.yaml under runtimes.code-interpreter ===\n")
    print(f"  code-interpreter:")
    print(f"    region: {args.region}")
    print(f"    code_interpreter_identifier: {ci_id}")
    print(f"    session_timeout_seconds: 900")
    print(f"    filesystem_configurations:")
    print(f"      - s3FilesConfiguration:")
    print(f"          accessPointArn: {ap_arn}")
    print(f"          fileSystemArn:  {fs_arn}")
    print(f"          mountPath: {args.mount_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

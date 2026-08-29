"""Bootstrap AWS resources for AgentCore CodeInterpreter with S3 Files mount.

Idempotent — reruns reuse resources named after --name.

Creates:
  1. IAM role for S3 Files service (reads/writes the backing S3 bucket)
  2. IAM role for AgentCore CodeInterpreter execution
  3. S3 Files file system rooted at s3://<bucket>/<prefix>
  4. Mount targets (one per --subnet)
  5. Access point (POSIX 1000:1000, root=/)
  6. Inline s3files:ClientMount / ClientWrite / GetAccessPoint policy on
     the CI role scoped to the access point ARN
  7. Custom AgentCore CodeInterpreter with networkMode=VPC and
     filesystemConfigurations pointing at the access point

Prints the yaml block to paste into service/workspaces.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Callable

import boto3
from botocore.exceptions import ClientError


AGENTCORE_TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def s3files_trust(account_id: str, region: str) -> dict:
    """S3 Files runs on EFS infrastructure — service principal is
    elasticfilesystem.amazonaws.com, scoped by source arn + account."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowS3FilesAssumeRole",
                "Effect": "Allow",
                "Principal": {"Service": "elasticfilesystem.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:s3files:{region}:{account_id}:file-system/*"
                    },
                },
            }
        ],
    }


def s3files_service_policy(bucket: str, account_id: str) -> dict:
    bucket_arn = f"arn:aws:s3:::{bucket}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3BucketPermissions",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:ListBucketVersions"],
                "Resource": bucket_arn,
                "Condition": {"StringEquals": {"aws:ResourceAccount": account_id}},
            },
            {
                "Sid": "S3ObjectPermissions",
                "Effect": "Allow",
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:DeleteObject*",
                    "s3:GetObject*",
                    "s3:List*",
                    "s3:PutObject*",
                ],
                "Resource": f"{bucket_arn}/*",
                "Condition": {"StringEquals": {"aws:ResourceAccount": account_id}},
            },
            {
                "Sid": "EventBridgeManage",
                "Effect": "Allow",
                "Action": [
                    "events:DeleteRule", "events:DisableRule", "events:EnableRule",
                    "events:PutRule", "events:PutTargets", "events:RemoveTargets",
                ],
                "Condition": {
                    "StringEquals": {"events:ManagedBy": "elasticfilesystem.amazonaws.com"}
                },
                "Resource": "arn:aws:events:*:*:rule/DO-NOT-DELETE-S3-Files*",
            },
            {
                "Sid": "EventBridgeRead",
                "Effect": "Allow",
                "Action": [
                    "events:DescribeRule", "events:ListRuleNamesByTarget",
                    "events:ListRules", "events:ListTargetsByRule",
                ],
                "Resource": "arn:aws:events:*:*:rule/*",
            },
        ],
    }


def ci_client_mount_policy(fs_arn: str, ap_arn: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "MountAndWrite",
                "Effect": "Allow",
                "Action": ["s3files:ClientMount", "s3files:ClientWrite"],
                "Resource": fs_arn,
                "Condition": {"ArnEquals": {"s3files:AccessPointArn": ap_arn}},
            },
            {
                "Sid": "DescribeAccessPoint",
                "Effect": "Allow",
                "Action": "s3files:GetAccessPoint",
                "Resource": ap_arn,
            },
            {
                "Sid": "DescribeFileSystem",
                "Effect": "Allow",
                "Action": [
                    "s3files:GetFileSystem",
                    "s3files:GetMountTarget",
                    "s3files:ListMountTargets",
                    "s3files:DescribeMountTargets",
                    "s3files:ListAccessPoints",
                    "s3files:ListFileSystems",
                ],
                "Resource": "*",
            },
        ],
    }


def ensure_role(iam, name: str, trust: dict, description: str) -> str:
    try:
        r = iam.get_role(RoleName=name)
        # Update trust policy in case it drifted (e.g. earlier bootstrap
        # attempt wrote the wrong principal).
        iam.update_assume_role_policy(RoleName=name, PolicyDocument=json.dumps(trust))
        return r["Role"]["Arn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
    r = iam.create_role(
        RoleName=name,
        AssumeRolePolicyDocument=json.dumps(trust),
        Description=description,
    )
    return r["Role"]["Arn"]


def put_inline_policy(iam, role: str, policy_name: str, policy: dict) -> None:
    iam.put_role_policy(
        RoleName=role, PolicyName=policy_name, PolicyDocument=json.dumps(policy)
    )


def find_file_system(s3files, name: str, bucket: str, prefix: str):
    bucket_arn = f"arn:aws:s3:::{bucket}"
    want_prefix = prefix.strip("/")
    for page in s3files.get_paginator("list_file_systems").paginate(bucket=bucket_arn):
        for summary in page.get("fileSystems", []) or []:
            fs = s3files.get_file_system(fileSystemId=summary["fileSystemId"])
            got_prefix = (fs.get("prefix") or "").strip("/")
            if got_prefix == want_prefix:
                return fs
    return None


def ensure_file_system(s3files, name: str, bucket: str, prefix: str, role_arn: str) -> dict:
    existing = find_file_system(s3files, name, bucket, prefix)
    if existing:
        return existing
    kwargs = dict(
        bucket=f"arn:aws:s3:::{bucket}",
        roleArn=role_arn,
        acceptBucketWarning=True,
        tags=[{"key": "name", "value": name}],
    )
    normalized_prefix = prefix.strip("/")
    if normalized_prefix:
        kwargs["prefix"] = f"{normalized_prefix}/"  # API requires trailing / or empty
    r = s3files.create_file_system(**kwargs)
    fs_id = r["fileSystemId"]
    _wait(lambda: _fs_state(s3files, fs_id) == "AVAILABLE", "S3 Files fs AVAILABLE", 600)
    return s3files.get_file_system(fileSystemId=fs_id)


def existing_mount_target_ids(s3files, fs_id: str) -> dict[str, str]:
    """Return {subnet_id: mount_target_id}."""
    out: dict[str, str] = {}
    for page in s3files.get_paginator("list_mount_targets").paginate(fileSystemId=fs_id):
        for mt in page.get("mountTargets", []) or []:
            out[mt["subnetId"]] = mt["mountTargetId"]
    return out


def ensure_mount_targets(s3files, fs_id: str, subnet_ids: list[str], sg_id: str) -> list[str]:
    existing = existing_mount_target_ids(s3files, fs_id)
    mt_ids: list[str] = []
    for sn in subnet_ids:
        if sn in existing:
            mt_ids.append(existing[sn])
            continue
        r = s3files.create_mount_target(
            fileSystemId=fs_id, subnetId=sn, securityGroups=[sg_id],
        )
        mt_ids.append(r["mountTargetId"])
    for mt_id in mt_ids:
        _wait(lambda mt_id=mt_id: _mt_state(s3files, mt_id) == "AVAILABLE",
              f"mount target {mt_id} AVAILABLE", 600)
    return mt_ids


def ensure_access_point(s3files, fs_id: str, name: str) -> str:
    for page in s3files.get_paginator("list_access_points").paginate(fileSystemId=fs_id):
        for ap in page.get("accessPoints", []) or []:
            if ap.get("name") == name:
                return ap["accessPointArn"]
    r = s3files.create_access_point(
        fileSystemId=fs_id,
        posixUser={"uid": 1000, "gid": 1000},
        rootDirectory={
            "path": "/",
            "creationPermissions": {"ownerUid": 1000, "ownerGid": 1000, "permissions": "755"},
        },
        tags=[{"key": "name", "value": name}],
    )
    return r["accessPointArn"]


def ensure_code_interpreter(
    cp, name: str, role_arn: str, subnet_ids: list[str], sg_id: str,
    fs_arn: str, ap_arn: str, mount_path: str,
) -> str:
    """Return the code interpreter ID (not ARN — data plane requires ID)."""
    for page in cp.get_paginator("list_code_interpreters").paginate():
        for ci in page.get("codeInterpreterSummaries", []) or []:
            if ci.get("name") == name:
                ci_id = ci.get("codeInterpreterId") or name
                _wait_ci_ready(cp, ci_id)
                return ci_id
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
    ci_id = r.get("codeInterpreterId") or name
    _wait_ci_ready(cp, ci_id)
    return ci_id


def _wait_ci_ready(cp, ci_id: str) -> None:
    _wait(
        lambda: (cp.get_code_interpreter(codeInterpreterId=ci_id).get("status") or "").upper() == "READY",
        f"code interpreter {ci_id} READY",
        600,
    )


def _fs_state(s3files, fs_id: str) -> str:
    try:
        return (s3files.get_file_system(fileSystemId=fs_id).get("status") or "").upper()
    except ClientError:
        return ""


def _mt_state(s3files, mt_id: str) -> str:
    try:
        return (s3files.get_mount_target(mountTargetId=mt_id).get("status") or "").upper()
    except ClientError:
        return ""


def _wait(check: Callable[[], bool], what: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(3)
    raise TimeoutError(f"timed out waiting for {what}")


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
    account_id = boto3.client("sts").get_caller_identity()["Account"]

    print(f"[1/6] IAM role for S3 Files service", flush=True)
    s3files_role = f"{args.name}-s3files-role"
    s3files_role_arn = ensure_role(iam, s3files_role,
                                   s3files_trust(account_id, args.region),
                                   "S3 Files service role")
    put_inline_policy(iam, s3files_role, "s3-access",
                      s3files_service_policy(args.s3_bucket, account_id))
    print(f"     {s3files_role_arn}")

    print(f"[2/6] IAM role for AgentCore CodeInterpreter", flush=True)
    ci_role = f"{args.name}-ci-role"
    ci_role_arn = ensure_role(iam, ci_role, AGENTCORE_TRUST, "AgentCore CI execution role")
    print(f"     {ci_role_arn}")

    print(f"[3/6] S3 Files fs {args.name}-fs (bucket={args.s3_bucket}, prefix={args.s3_prefix})",
          flush=True)
    fs = ensure_file_system(s3files, f"{args.name}-fs", args.s3_bucket, args.s3_prefix,
                            s3files_role_arn)
    print(f"     {fs['fileSystemArn']}")

    print(f"[4/6] mount targets in {len(subnet_ids)} subnet(s)", flush=True)
    mt_ids = ensure_mount_targets(s3files, fs["fileSystemId"], subnet_ids, args.security_group_id)
    for mt in mt_ids:
        print(f"     {mt}")

    print(f"[5/6] access point {args.name}-ap", flush=True)
    ap_arn = ensure_access_point(s3files, fs["fileSystemId"], f"{args.name}-ap")
    put_inline_policy(iam, ci_role, "s3files-mount",
                      ci_client_mount_policy(fs["fileSystemArn"], ap_arn))
    print(f"     {ap_arn}")

    # IAM policy propagation lag — brief wait so the next call sees the perm.
    print("     waiting 15s for IAM propagation...", flush=True)
    time.sleep(15)

    print(f"[6/6] AgentCore code interpreter {args.name}-ci", flush=True)
    ci_id = ensure_code_interpreter(
        cp, f"{args.name.replace('-', '_')}_ci", ci_role_arn, subnet_ids, args.security_group_id,
        fs["fileSystemArn"], ap_arn, args.mount_path,
    )
    print(f"     {ci_id}")

    print("\n=== paste into service/workspaces.yaml → runtimes.code-interpreter ===\n")
    print(f"  code-interpreter:")
    print(f"    region: {args.region}")
    print(f"    # /mnt/s3data → S3 Files → s3://{args.s3_bucket}/{args.s3_prefix.strip('/')}/")
    print(f"    # Mount baked in at CI create time; no filesystem_configurations here.")
    print(f"    code_interpreter_identifier: {ci_id}")
    print(f"    session_timeout_seconds: 900")
    return 0


if __name__ == "__main__":
    sys.exit(main())

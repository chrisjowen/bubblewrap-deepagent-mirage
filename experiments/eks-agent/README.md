# EKS Fargate deployment

Experimental target — run the same deepagents + mirage agent on EKS Fargate
instead of Bedrock AgentCore.

## Layout

```
eks/
├── cluster.yaml           # eksctl cluster spec (Fargate-only)
├── app/
│   ├── Dockerfile         # build context = repo root
│   ├── main.py            # FastAPI SSE endpoint
│   ├── agent.py           # env-driven agent (no AgentCore SDK)
│   └── pyproject.toml
└── k8s/
    ├── namespace.yaml
    ├── secret.example.yaml
    ├── deployment.yaml    # replicas: 1 (InMemorySaver is per-pod)
    ├── service.yaml
    └── ingress.yaml       # ALB, internet-facing
```

## API

- `GET /healthz` → `200 ok`
- `POST /invoke`
  - Body: `{"prompt": "..."}`
  - Header: `X-Session-Id: <string>` (optional; defaults to `default`)
  - Response: `text/event-stream` — one chunk per model text delta.

## One-time setup

Install tools:

```bash
brew install eksctl awscli kubectl helm
```

Log in to AWS and set region:

```bash
aws configure
export AWS_REGION=us-east-1
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
```

Create the cluster (~15–25 min):

```bash
eksctl create cluster -f eks/cluster.yaml
```

Install the AWS Load Balancer Controller (required for ALB ingress on
Fargate — the in-tree cloud provider does not create ALBs):

```bash
# IAM policy
curl -s https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json \
  -o iam-policy.json
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam-policy.json || true

# Service account bound to the policy
eksctl create iamserviceaccount \
  --cluster=ada-eks \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --attach-policy-arn=arn:aws:iam::${ACCOUNT}:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve

# Helm install
helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=ada-eks \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

Create ECR repo:

```bash
aws ecr create-repository --repository-name ada-eks
```

## Build + push image

Run from the **repo root** (Dockerfile expects that as build context):

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin \
  ${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com

docker build -f eks/app/Dockerfile -t ada-eks:latest .
docker tag ada-eks:latest ${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/ada-eks:latest
docker push ${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/ada-eks:latest
```

## Deploy

Point kubectl at the cluster:

```bash
aws eks update-kubeconfig --name ada-eks --region ${AWS_REGION}
```

Create namespace + secret:

```bash
kubectl apply -f eks/k8s/namespace.yaml
kubectl -n ada create secret generic ada-env --from-env-file=.env
```

Substitute account/region in the deployment image field then apply:

```bash
sed "s|ACCOUNT.dkr.ecr.REGION|${ACCOUNT}.dkr.ecr.${AWS_REGION}|" \
    eks/k8s/deployment.yaml | kubectl apply -f -
kubectl apply -f eks/k8s/service.yaml
kubectl apply -f eks/k8s/ingress.yaml
```

Wait for pod + ALB:

```bash
kubectl -n ada rollout status deploy/ada
kubectl -n ada get ingress ada -w   # wait until ADDRESS is populated
```

## Test

```bash
ALB=$(kubectl -n ada get ingress ada -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

curl -N -X POST "http://${ALB}/invoke" \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: test-1' \
  -d '{"prompt":"list files under /skills"}'
```

Send a follow-up on the same session — history persists (in-memory) as
long as the pod stays up:

```bash
curl -N -X POST "http://${ALB}/invoke" \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: test-1' \
  -d '{"prompt":"which one did I ask about first?"}'
```

## Known limitations

- **Session state is in-memory, per-pod.** `replicas: 1` + `strategy: Recreate`
  means a single pod handles every session and a rollout drops history. For
  more pods add sticky sessions on the ALB (`alb.ingress.kubernetes.io/target-group-attributes:
  stickiness.enabled=true,stickiness.type=lb_cookie`) OR swap `InMemorySaver`
  for a shared checkpointer.
- **No isolation of `execute`.** Fargate itself is the microVM boundary
  (each pod = firecracker VM), so we use `LocalShellBackend`. Bubblewrap
  won't work on Fargate (no CAP_SYS_ADMIN). If you drop this on regular
  EC2 nodes, swap in `BwrapBackend`.
- **S3 credentials in a k8s Secret.** OK for the experiment. Production
  should use IRSA — an IAM role bound to a `ServiceAccount`, no long-lived
  keys.
- **HTTP only on the ALB.** Add ACM cert + `listen-ports` HTTPS entry for TLS.

## Teardown

```bash
kubectl delete -f eks/k8s/ingress.yaml       # deletes the ALB
eksctl delete cluster -f eks/cluster.yaml    # deletes cluster + Fargate profile
aws ecr delete-repository --repository-name ada-eks --force
```

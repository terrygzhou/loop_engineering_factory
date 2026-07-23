---
name: production-deployment
description: Production deployment targeting cloud platforms — AWS, Azure, GCP configuration generation and deployment strategies
category: devops
---

# Production Deployment

## Purpose

Generate production-ready deployment configurations for cloud platforms. Separate from `docker-compose-deployment` (local dev scaffolding).

## Target Platforms

| Platform | Service | Key Artifacts |
|----------|---------|---------------|
| **AWS** | ECS/Fargate, EKS, RDS, CloudFront | `ecs-task-def.json`, `aws-lb.tf`, RDS instance |
| **Azure** | App Service, AKS, Azure SQL, Front Door | `azuredeploy.json`, `k8s-deployment.yaml`, SQL managed instance |
| **GCP** | Cloud Run, GKE, Cloud SQL, Cloud LB | `cloudbuild.yaml`, `k8s-deployment.yaml`, Cloud SQL instance |

## Deployment Pipeline

```
Local (docker-compose-dev.yml) → CI/CD → Cloud platform (production config)
```

### Environment Separation

| Aspect | Local Dev | Production |
|--------|-----------|------------|
| DB | SQLite / local PostgreSQL | Managed RDS/Azure SQL/Cloud SQL |
| Cache | Local Redis | ElastiCache/Redis Enterprise |
| Secrets | `.env` file | AWS Secrets Manager/Azure Key Vault/GCP Secret Manager |
| TLS | Self-signed / dev cert | ACME (Let's Encrypt) / Cloud cert |
| Scaling | Single container | Auto-scaling group / HPA |
| Monitoring | Local logs / Grafana | CloudWatch/Application Insights/Cloud Monitoring |
| CI/CD | Manual `docker compose up` | GitHub Actions / GitLab CI / Cloud Build |

## AWS Deployment (ECS + Fargate)

### Infrastructure

```hcl
# ecs-task-def.json — Fargate task definition
{
  "family": "app",
  "networkMode": "awsvpc",
  "cpu": 1024,
  "memory": 2048,
  "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::ACCOUNT:role/appTaskRole",
  "containerDefinitions": [{
    "name": "app",
    "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/app:TAG",
    "portMappings": [{"containerPort": 8000, "protocol": "TCP"}],
    "environment": [
      {"name": "ENVIRONMENT", "value": "production"},
      {"name": "DATABASE_URL", "value": "${DATABASE_URL}"}
    ],
    "secrets": [
      {"name": "JWT_SECRET", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:app/jwt"},
      {"name": "STRIPE_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:app/stripe"}
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/app",
        "awslogs-region": "REGION",
        "awslogs-stream-prefix": "ecs"
      }
    }
  }]
}
```

### CI/CD Pipeline (GitHub Actions)

```yaml
name: Deploy to ECS
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t app:${{ github.sha }} .
      - run: aws ecr get-login-password | docker login --password-stdin
      - run: docker tag app:${{ github.sha }} ACCOUNT.dkr.ecr.REGION.amazonaws.com/app:${{ github.sha }}
      - run: docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/app:${{ github.sha }}
      - run: aws ecs update-service --cluster app --service app --force-new-deployment
```

## Azure Deployment (App Service)

### Configuration

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "resources": [
    {
      "type": "Microsoft.Web/sites",
      "apiVersion": "2022-03-01",
      "name": "app-prod",
      "location": "[resourceGroup().location]",
      "sku": {"name": "P1v3", "tier": "PremiumV3"},
      "properties": {
        "httpsOnly": true,
        "siteConfig": {
          "linuxFxVersion": "DOCKER|ACCOUNT.azurecr.io/app:TAG",
          "appSettings": [
            {"name": "WEBSITES_ENABLE_APP_SERVICE_NETWORKING", "value": "true"},
            {"name": "DOCKER_REGISTRY_SERVER_URL", "value": "https://ACCOUNT.azurecr.io"},
            {"name": "DOCKER_REGISTRY_SERVER_USERNAME", "value": "ACCOUNT"},
            {"name": "DOCKER_REGISTRY_SERVER_PASSWORD", "value": "[parameters('acrPassword')]"}
          ]
        }
      }
    }
  ]
}
```

## GCP Deployment (Cloud Run)

### Configuration

```yaml
# cloudbuild.yaml — Cloud Build trigger
steps:
  - name: "gcr.io/cloud-builders/docker"
    args: ["build", "-t", "gcr.io/PROJECT/app:${_TAG}", "."]
  - name: "gcr.io/cloud-builders/gcloud"
    args: ["run", "deploy", "app", "--image", "gcr.io/PROJECT/app:${_TAG}", "--region", "us-central1"]
```

```yaml
# service.yaml — Cloud Run service config
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: app
spec:
  template:
    spec:
      containers:
        - image: gcr.io/PROJECT/app:TAG
          ports: [{containerPort: 8000}]
          resources:
            limits: {cpu: "1", memory: "2Gi"}
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: database_url
```

## Secrets Management

| Platform | Tool | Command |
|----------|------|---------|
| AWS | Secrets Manager | `aws secretsmanager create-secret --name app/jwt --secret-string "..."` |
| Azure | Key Vault | `az keyvault secret set --vault-name KV --name jwt --value "..."` |
| GCP | Secret Manager | `echo "..." \| gcloud secrets versions add app-secrets --data-file=-` |

## Health Checks & Rollbacks

### Health check endpoint
Production deployment MUST include `/health` endpoint for:
- Load balancer health probing
- Auto-scaling readiness checks
- Deployment pipeline verification

### Rollback strategy
- **AWS ECS:** Redeploy previous task definition revision
- **Azure:** Rollback to previous deployment slot (`app-prod-staging` ↔ `app-prod`)
- **GCP:** Redeploy previous revision (`gcloud run deploy --revision-name=...`)

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container crashes on cloud | `.env` not available in production | Use cloud secret references, not env files |
| DB connection fails | Internal DNS vs public endpoint | Use private subnet endpoint for RDS/Azure SQL/Cloud SQL |
| TLS cert missing | Dev self-signed cert doesn't work in prod | ACME cert on ALB / Cloud cert on Cloud Run |
| Port mismatch | Dev maps 8000:8000, cloud expects container port | Ensure Dockerfile exposes correct port |
| Memory limits too low | Dev has unlimited, cloud has hard limits | Set realistic limits (2Gi minimum for Python + FastAPI + DB pool) |
| Log rotation missing | Local dev works fine, cloud fills disk | Configure cloud-native logging (CloudWatch/Stackdriver/AI) |

## Related Skills

- `docker-compose-deployment` — local dev scaffolding (compose files, hot-deploy)
- `observability-and-instrumentation` — production monitoring setup
- `shipping-and-launch` — pre-launch checklist, feature flags, rollback plans
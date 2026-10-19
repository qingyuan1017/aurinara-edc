# AWS deployment: Aurinara EDC consumer

Aurinara EDC is a consumer of the matching `aurinara-platform` environment
stack. It uses that environment's VPC and private subnets, while retaining its
own security groups, PostgreSQL database, KMS key, attachment and SPA buckets,
projection queue/DLQ, ECS API/projection/export services, CloudFront,
backup, alarms, and budget. Shared networking, Cognito, the Platform-owned
suite CloudTrail,
event bus, ALB, and WAF remain Platform-owned in the production budget profile.
The authoritative cross-repository topology, cost envelope, cutover order, and
rollback procedure are in
`aurinara-platform/docs/budget-deployment-profile.md`.

## Bootstrap

Read `GitHubOidcProviderArn` from `aurinara-platform-bootstrap`, then run:

```bash
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name aurinara-edc-bootstrap \
  --template-file infra/cloudformation/bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOwner=<owner> \
    GitHubRepository=aurinara-edc \
    DeploymentBranch=main \
    GitHubOidcProviderArn=<platform-bootstrap-output>
```

Configure both GitHub environments with the bootstrap outputs:
`AWS_DEPLOYMENT_ROLE_ARN`, `CLOUDFORMATION_EXECUTION_ROLE_ARN`,
`APPLICATION_REPOSITORY_URI`, and `TEMPLATE_BUCKET_NAME`. Also configure
`BASE_DOMAIN`, `CERTIFICATE_ARN`, `DNS_PROVIDER=cloudflare`,
`CLOUDFLARE_ZONE_ID`; store `CLOUDFLARE_API_TOKEN` as an environment secret.
`ALARM_EMAIL` is optional; when omitted, alarms and dashboards are created
without email or budget subscriptions.

The image-build job authenticates from the configured deployment branch and does
not bind itself to a protected environment. The bootstrap role therefore trusts
the exact branch OIDC subject as well as the `staging` and `production`
environment subjects. Staging and production deployment jobs retain their
environment protection rules; only the production gate is reached on a normal
push to `main`.

## Deploy

The matching Platform stack must already exist. Standard deployments require
its PrivateLink private-DNS state to be `verified`; budget deployments use the
Platform shared ALB. On a merge to `main`, the delivery workflow builds and
scans one digest, queries the production Platform outputs, takes an RDS snapshot,
deploys EDC production after approval, runs all Alembic migrations plus built-in
role seeding, activates the services, publishes the frontend, and runs readiness
checks. A manual run with `deploy_staging=true` performs the staging rehearsal
first.

Staging is `https://edc-staging.<base-domain>`; production is
`https://edc.<base-domain>`. Cloudflare records stay DNS-only. The browser calls
EDC through its own CloudFront distribution and calls the Platform Repository
through the Platform public URL. Backend authorization and object operations use
PrivateLink in `standard` and the shared internal ALB in `budget`.

In the standard profile the projection service long-polls the environment SQS queue. In
the budget profile EventBridge starts a drain-to-empty projection task every
minute and an export task every five minutes on Fargate Spot. An EventBridge rule
on the Platform bus targets that queue, the queue policy allows only that rule,
and failed messages redrive after five receives. The export service uses the
database-backed durable export queue and writes immutable attachments through
the task role; no static AWS credentials are injected.

## Release safety

- Images must be digest-pinned; mutable tags are rejected by CloudFormation.
- ECS services remain at zero until migrations and role seeding succeed.
- Standard production uses Multi-AZ RDS and 35-day backups. Budget production
  uses a separate Single-AZ `db.t4g.small` database, 14-day backups, one API
  task, and scheduled workers. Both profiles keep deletion protection, retained
  versioned S3, AWS Backup, encrypted logs, Platform-owned CloudTrail management
  and S3 object data events, alarms, and termination protection.
- Backup vault names use the unique nested-stack name so retained recovery
  points cannot create a name conflict during clean stack replacement.
- Retained application, frontend, and access-log buckets use
  CloudFormation-generated names so retained data cannot block clean stack
  replacement. Read their physical names from the environment stack outputs.
- The retained application log group also uses a CloudFormation-generated name
  so a prior rollback cannot block compute-stack recreation.
- Roll back services to a previous image digest only. Use expand/contract and
  forward repair for schema changes; never auto-restore the database.
- Test RDS point-in-time restore and S3 version/AWS Backup restore before launch
  and quarterly.

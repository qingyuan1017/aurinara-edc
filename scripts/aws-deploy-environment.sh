#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?missing stack name}
environment=${2:?missing environment}
vpc_cidr=${3:?missing VPC CIDR}
database_class=${4:?missing database class}
dns_provider=${DNS_PROVIDER:-cloudflare}
hosted_zone_id=${HOSTED_ZONE_ID:-}
alarm_email=${ALARM_EMAIL:-}

required=(APPLICATION_IMAGE BASE_DOMAIN CERTIFICATE_ARN PLATFORM_STACK_NAME CLOUDFORMATION_EXECUTION_ROLE_ARN)
for name in "${required[@]}"; do [[ -n "${!name:-}" ]] || { echo "$name is required" >&2; exit 1; }; done
[[ "$dns_provider" == cloudflare || "$dns_provider" == route53 ]] || { echo "DNS_PROVIDER must be cloudflare or route53" >&2; exit 1; }
[[ "$dns_provider" != route53 || -n "$hosted_zone_id" ]] || { echo "HOSTED_ZONE_ID is required for Route 53" >&2; exit 1; }

platform_output() {
  aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

vpc_id=$(platform_output VpcId)
vpc_cidr=$(platform_output VpcCidr)
app_subnet_ids=$(platform_output AppSubnetIds)
runner_subnet_ids=$(platform_output RunnerSubnetIds)
data_subnet_ids=$(platform_output DataSubnetIds)
platform_private_url=$(platform_output PlatformPrivateUrl)
platform_public_url=$(platform_output PlatformUrl)
event_bus=$(platform_output EventBusName)
identity_key=$(platform_output SharedIdentityKeyArn)
user_pool=$(platform_output UserPoolId)
spa_client=$(platform_output EdcSpaClientId)
jwt_issuer=$(platform_output JwtIssuer)
jwks_url=$(platform_output JwtJwksUrl)
cognito_domain=$(platform_output CognitoDomain)
token_url=$(platform_output TokenUrl)
service_client=$(platform_output EdcServiceClientId)
service_secret=$(platform_output EdcServiceClientSecretArn)

deploy() {
  local service_image=$1
  local migration_image=$2
  local enabled=$3
  aws cloudformation deploy \
    --template-file packaged.yaml \
    --stack-name "$stack_name" \
    --role-arn "$CLOUDFORMATION_EXECUTION_ROLE_ARN" \
    --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
      Environment="$environment" VpcCidr="$vpc_cidr" VpcId="$vpc_id" \
      AppSubnetIds="$app_subnet_ids" RunnerSubnetIds="$runner_subnet_ids" DataSubnetIds="$data_subnet_ids" BaseDomain="$BASE_DOMAIN" \
      DnsProvider="$dns_provider" HostedZoneId="$hosted_zone_id" CertificateArn="$CERTIFICATE_ARN" \
      ApplicationImage="$service_image" MigrationApplicationImage="$migration_image" DatabaseInstanceClass="$database_class" AlarmEmail="$alarm_email" ServicesEnabled="$enabled" \
      PlatformPrivateUrl="$platform_private_url" PlatformPublicUrl="$platform_public_url" PlatformEventBusName="$event_bus" \
      SharedIdentityKeyArn="$identity_key" UserPoolId="$user_pool" SpaClientId="$spa_client" JwtIssuer="$jwt_issuer" JwtJwksUrl="$jwks_url" \
      CognitoDomain="$cognito_domain" ServiceTokenUrl="$token_url" ServiceClientId="$service_client" ServiceClientSecretArn="$service_secret"
}

current_image=$APPLICATION_IMAGE
services_enabled=false
if aws cloudformation describe-stacks --stack-name "$stack_name" >/dev/null 2>&1; then
  stack_status=""
  for _ in {1..90}; do
    stack_status=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query 'Stacks[0].StackStatus' --output text)
    [[ "$stack_status" == *_IN_PROGRESS ]] || break
    sleep 10
  done
  if [[ "$stack_status" == *_IN_PROGRESS ]]; then
    echo "Timed out waiting for ${stack_name} to finish ${stack_status}" >&2
    exit 1
  fi
  current_image=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Parameters[?ParameterKey=='ApplicationImage'].ParameterValue" --output text)
  services_enabled=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Parameters[?ParameterKey=='ServicesEnabled'].ParameterValue" --output text)
  [[ "$services_enabled" == true ]] || services_enabled=false
fi

deploy "$current_image" "$APPLICATION_IMAGE" "$services_enabled"
cluster=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Outputs[?OutputKey=='ClusterName'].OutputValue" --output text)
task=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Outputs[?OutputKey=='MigrationTaskDefinitionArn'].OutputValue" --output text)
subnets=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Outputs[?OutputKey=='AppSubnetIds'].OutputValue" --output text)
security_group=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query "Stacks[0].Outputs[?OutputKey=='WorkerSecurityGroupId'].OutputValue" --output text)
run_arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$task" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" --query 'tasks[0].taskArn' --output text)
[[ "$run_arn" != None && -n "$run_arn" ]] || { echo "migration task did not start" >&2; exit 1; }
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$run_arn"
exit_code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$run_arn" --query "tasks[0].containers[?name=='migration'].exitCode | [0]" --output text)
[[ "$exit_code" == 0 ]] || { echo "migration failed with exit code $exit_code" >&2; exit 1; }
deploy "$APPLICATION_IMAGE" "$APPLICATION_IMAGE" true

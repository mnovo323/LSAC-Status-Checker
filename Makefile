.PHONY: setup run deploy-all update-all update-code update-stack logs test teardown update-credentials clean help

# Configuration
AWS_REGION ?= us-east-1
ECR_REPO_NAME ?= lsac-status-checker
STACK_NAME ?= lsac-status-checker
IMAGE_TAG ?= latest

# Source .env file if it exists to get AWS_PROFILE and other settings
ifneq (,$(wildcard .env))
    include .env
    export
endif

# AWS_PROFILE can be overridden via command line or from .env
AWS_PROFILE ?=

# Set up AWS CLI options based on whether profile is specified
AWS_CLI_OPTS = $(if $(AWS_PROFILE),--profile $(AWS_PROFILE),)
AWS_ACCOUNT_ID ?= $(shell aws sts get-caller-identity $(AWS_CLI_OPTS) --query Account --output text 2>/dev/null)

ECR_URI = $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/$(ECR_REPO_NAME)
IMAGE_URI = $(ECR_URI):$(IMAGE_TAG)

###################
# Local Development
###################

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/playwright install chromium
	@echo ""
	@echo "✅ Setup complete!"
	@echo "   Next: make run"

run:
	@if [ ! -d ".venv" ]; then \
		echo "❌ Virtual environment not found."; \
		echo "   Run: make setup"; \
		exit 1; \
	fi
	@if [ ! -f ".env" ]; then \
		echo "❌ .env file not found."; \
		echo "   Create .env with:"; \
		echo "     LSAC_USERNAME=your_username"; \
		echo "     LSAC_PASSWORD=your_password"; \
		exit 1; \
	fi
	@if [ ! -f "schools.txt" ]; then \
		echo "❌ schools.txt not found."; \
		echo "   Create schools.txt with your school status checker URLs"; \
		exit 1; \
	fi
	.venv/bin/python lsac_checker.py

################
# AWS Deployment
################

deploy-all:
	@if [ -z "$(EMAIL)" ]; then \
		echo "❌ EMAIL not specified"; \
		echo "   Usage: make deploy-all EMAIL=your@email.com"; \
		exit 1; \
	fi
	@echo "🚀 Starting complete AWS deployment..."
	@echo ""
	@$(MAKE) -s _build
	@$(MAKE) -s _deploy EMAIL=$(EMAIL)
	@$(MAKE) -s _upload-schools
	@echo ""
	@echo "🎉 Deployment complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Check your email and confirm SNS subscription"
	@echo "  2. View logs: make logs"
	@echo "  3. Test: make test"

update-code:
	@echo "🔄 Updating Lambda code..."
	@$(MAKE) -s _build
	@$(MAKE) -s _update
	@echo "✅ Code update complete!"

update-stack:
	@echo "🔄 Updating CloudFormation stack..."
	@$(MAKE) -s _update_cloudformation
	@echo "✅ Stack update complete!"

update-all:
	@echo "🔄 Updating Lambda code and stack..."
	@$(MAKE) -s _build
	@$(MAKE) -s _update
	@$(MAKE) -s _update_cloudformation
	@echo "✅ Update complete!"

logs:
	@FUNCTION_NAME=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`FunctionName`].OutputValue' --output text 2>/dev/null) && \
	if [ -z "$$FUNCTION_NAME" ]; then \
		echo "❌ Stack not found. Run 'make deploy-all EMAIL=your@email.com' first"; \
		exit 1; \
	fi && \
	aws logs tail $(AWS_CLI_OPTS) /aws/lambda/$$FUNCTION_NAME --follow

test:
	@echo "🧪 Testing Lambda function..."
	@FUNCTION_NAME=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`FunctionName`].OutputValue' --output text 2>/dev/null) && \
	if [ -z "$$FUNCTION_NAME" ]; then \
		echo "❌ Stack not found. Run 'make deploy-all EMAIL=your@email.com' first"; \
		exit 1; \
	fi && \
	aws lambda invoke $(AWS_CLI_OPTS) --function-name $$FUNCTION_NAME response.json > /dev/null && \
	cat response.json && rm -f response.json

upload-schools:
	@if [ ! -f "schools.txt" ]; then \
		echo "❌ schools.txt not found"; \
		exit 1; \
	fi
	@BUCKET=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' --output text 2>/dev/null) && \
	if [ -z "$$BUCKET" ]; then \
		echo "❌ Stack not found. Run 'make deploy-all EMAIL=your@email.com' first"; \
		exit 1; \
	fi && \
	aws s3 cp $(AWS_CLI_OPTS) schools.txt s3://$$BUCKET/schools.txt && \
	echo "✅ Uploaded schools.txt to S3"

update-credentials:
	@if [ ! -f ".env" ]; then \
		echo "❌ .env file not found"; \
		exit 1; \
	fi
	@SECRET_ID=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`CredentialsSecretName`].OutputValue' --output text 2>/dev/null) && \
	if [ -z "$$SECRET_ID" ]; then \
		echo "❌ Stack not found. Run 'make deploy-all EMAIL=your@email.com' first"; \
		exit 1; \
	fi && \
	LSAC_USERNAME=$$(grep LSAC_USERNAME .env | cut -d= -f2) && \
	LSAC_PASSWORD=$$(grep LSAC_PASSWORD .env | cut -d= -f2) && \
	aws secretsmanager update-secret $(AWS_CLI_OPTS) \
		--secret-id $$SECRET_ID \
		--secret-string "{\"username\":\"$$LSAC_USERNAME\",\"password\":\"$$LSAC_PASSWORD\"}" \
		>/dev/null 2>&1 && \
	echo "✅ Updated credentials in Secrets Manager"

_update_cloudformation:
	@echo "🕐 Updating CloudFormation stack..."
	@STACK_STATUS=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].StackStatus' --output text 2>/dev/null) && \
	if [ -z "$$STACK_STATUS" ]; then \
		echo "❌ Stack not found. Run 'make deploy-all EMAIL=your@email.com' first"; \
		exit 1; \
	fi && \
	UPDATE_OUTPUT=$$(aws cloudformation update-stack $(AWS_CLI_OPTS) \
		--stack-name $(STACK_NAME) \
		--use-previous-template \
		--parameters \
			ParameterKey=ScheduleExpression,ParameterValue='cron(0 * * * ? *)' \
			ParameterKey=LSACUsername,UsePreviousValue=true \
			ParameterKey=LSACPassword,UsePreviousValue=true \
			ParameterKey=NotificationEmail,UsePreviousValue=true \
			ParameterKey=ECRImageUri,UsePreviousValue=true \
			ParameterKey=Timezone,ParameterValue=America/New_York \
		--capabilities CAPABILITY_NAMED_IAM \
		--region $(AWS_REGION) 2>&1) && \
	echo "⏳ Waiting for stack update..." && \
	aws cloudformation wait stack-update-complete $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --region $(AWS_REGION) && \
	echo "✅ CloudFormation stack updated" || \
	if echo "$$UPDATE_OUTPUT" | grep -q "No updates are to be performed"; then \
		echo "✅ CloudFormation stack already up to date"; \
	else \
		echo "$$UPDATE_OUTPUT"; \
		exit 1; \
	fi

teardown:
	@echo "⚠️  This will delete your Lambda function, S3 bucket, and all data"
	@read -p "Are you sure? [y/N] " confirm && \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		aws cloudformation delete-stack $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --region $(AWS_REGION) 2>/dev/null; \
		echo "🗑️  Deleting stack (this may take a few minutes)..."; \
		aws cloudformation wait stack-delete-complete $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) 2>/dev/null || true; \
		echo "✅ Stack deleted"; \
	else \
		echo "Cancelled"; \
	fi

####################
# Internal targets
####################

_build:
	@echo "🐳 Building Docker image..."
	@aws ecr get-login-password $(AWS_CLI_OPTS) --region $(AWS_REGION) 2>/dev/null | docker login --username AWS --password-stdin $(ECR_URI) 2>/dev/null || \
		(echo "❌ AWS not configured. Run: aws configure$(if $(AWS_PROFILE), --profile $(AWS_PROFILE),)"; exit 1)
	@docker build --platform linux/amd64 -q -t $(IMAGE_URI) . 2>/dev/null || \
		(echo "❌ Docker build failed"; exit 1)
	@aws ecr describe-repositories $(AWS_CLI_OPTS) --repository-names $(ECR_REPO_NAME) --region $(AWS_REGION) >/dev/null 2>&1 || \
		aws ecr create-repository $(AWS_CLI_OPTS) --repository-name $(ECR_REPO_NAME) --region $(AWS_REGION) >/dev/null 2>&1
	@docker push $(IMAGE_URI) >/dev/null 2>&1
	@echo "✅ Image built and pushed"

_deploy:
	@if [ ! -f ".env" ]; then \
		echo "❌ .env file not found"; \
		exit 1; \
	fi
	@LSAC_USERNAME=$$(grep LSAC_USERNAME .env | cut -d= -f2) && \
	LSAC_PASSWORD=$$(grep LSAC_PASSWORD .env | cut -d= -f2) && \
	if [ -z "$$LSAC_USERNAME" ] || [ -z "$$LSAC_PASSWORD" ]; then \
		echo "❌ LSAC_USERNAME or LSAC_PASSWORD not set in .env"; \
		exit 1; \
	fi
	@echo "📦 Deploying CloudFormation stack..."
	@aws cloudformation deploy $(AWS_CLI_OPTS) \
		--template-file cloudformation.yaml \
		--stack-name $(STACK_NAME) \
		--parameter-overrides \
			LSACUsername=$$(grep LSAC_USERNAME .env | cut -d= -f2) \
			LSACPassword=$$(grep LSAC_PASSWORD .env | cut -d= -f2) \
			NotificationEmail=$(EMAIL) \
			ECRImageUri=$(IMAGE_URI) \
			Timezone=$$(grep TIMEZONE .env 2>/dev/null | cut -d= -f2 | grep . || echo "America/New_York") \
		--capabilities CAPABILITY_NAMED_IAM \
		--region $(AWS_REGION) \
		--no-fail-on-empty-changeset >/dev/null 2>&1
	@echo "✅ Stack deployed"

_update:
	@echo "📤 Updating function code..."
	@FUNCTION_NAME=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`FunctionName`].OutputValue' --output text 2>/dev/null) && \
	aws lambda update-function-code $(AWS_CLI_OPTS) --function-name $$FUNCTION_NAME --image-uri $(IMAGE_URI) >/dev/null 2>&1 && \
	aws lambda wait function-updated $(AWS_CLI_OPTS) --function-name $$FUNCTION_NAME

_upload-schools:
	@if [ -f "schools.txt" ]; then \
		BUCKET=$$(aws cloudformation describe-stacks $(AWS_CLI_OPTS) --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' --output text 2>/dev/null) && \
		aws s3 cp $(AWS_CLI_OPTS) schools.txt s3://$$BUCKET/schools.txt 2>/dev/null && \
		echo "✅ Uploaded schools.txt to S3"; \
	fi

clean:
	rm -rf venv .venv token.json status_history.json response.json

help:
	@echo "LSAC Status Checker"
	@echo ""
	@echo "Local:"
	@echo "  make setup                     Setup local environment"
	@echo "  make run                       Run locally"
	@echo ""
	@echo "AWS Lambda:"
	@echo "  make deploy-all EMAIL=you@...  Complete deployment"
	@echo "  make update-code               Update Lambda code only"
	@echo "  make update-stack              Update CloudFormation stack only"
	@echo "  make update-all                Update code and stack"
	@echo "  make upload-schools            Upload schools.txt to S3"
	@echo "  make update-credentials        Update LSAC credentials"
	@echo "  make logs                      View logs"
	@echo "  make test                      Test function"
	@echo "  make teardown                  Delete everything"
	@echo ""
	@echo "Configuration:"
	@echo "  Stack:   $(STACK_NAME)"
	@echo "  Region:  $(AWS_REGION)"
	@echo "  Profile: $(if $(AWS_PROFILE),$(AWS_PROFILE),default)"
	@echo ""
	@echo "Optional parameters:"
	@echo "  AWS_PROFILE=profile-name  Use specific AWS profile"
	@echo "  AWS_REGION=region         Override default region"
	@echo ""
	@echo "Example:"
	@echo "  make deploy-all EMAIL=you@example.com AWS_PROFILE=myprofile"

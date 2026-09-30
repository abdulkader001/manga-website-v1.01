# Reference Terraform — managed Postgres (writer + reader), Redis, PgBouncer-style
# pooling. REFERENCE ONLY: no remote state, no hardening. Apply when you have a
# cloud account. AWS is shown; the shape is identical on GCP (Cloud SQL +
# Memorystore) or Azure (Flexible Server + Azure Cache).
#
#   terraform init && terraform plan
#
# Outputs feed the app's env: DATABASE_URL (writer), DATABASE_READ_URL (reader,
# item 32), REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "vpc_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for the DB/cache subnet groups."
}

variable "security_group_ids" {
  type        = list(string)
  description = "SGs allowing the app/worker pods to reach 5432 and 6379."
}

# ---------------------------------------------------------------------------
# Postgres: primary + a read replica. The app routes read-heavy endpoints to
# the replica via DATABASE_READ_URL (item 32) — set it to the replica endpoint.
# ---------------------------------------------------------------------------
resource "aws_db_subnet_group" "pg" {
  name       = "manga-pg"
  subnet_ids = var.vpc_subnet_ids
}

resource "aws_db_instance" "primary" {
  identifier              = "manga-pg-primary"
  engine                  = "postgres"
  engine_version          = "14"
  instance_class          = "db.r6g.xlarge" # size for ~100k users; right-size with metrics
  allocated_storage       = 100
  max_allocated_storage   = 500
  storage_type            = "gp3"
  username                = "manga"
  password                = var.db_password
  db_name                 = "manga"
  db_subnet_group_name    = aws_db_subnet_group.pg.name
  vpc_security_group_ids  = var.security_group_ids
  multi_az                = true
  backup_retention_period = 7
  storage_encrypted       = true
  # RDS Proxy (below) provides the pooling that PgBouncer gives us locally.
  skip_final_snapshot = false
  deletion_protection = true
}

resource "aws_db_instance" "replica" {
  identifier             = "manga-pg-replica"
  replicate_source_db    = aws_db_instance.primary.identifier
  instance_class         = "db.r6g.large"
  vpc_security_group_ids = var.security_group_ids
  storage_encrypted      = true
  skip_final_snapshot    = true
}

# ---------------------------------------------------------------------------
# Connection pooling — RDS Proxy is the managed PgBouncer equivalent. (Or run
# the PgBouncer sidecar from docker-compose.scale.yml as a k8s Deployment.)
# ---------------------------------------------------------------------------
resource "aws_db_proxy" "pool" {
  name                   = "manga-pg-pool"
  engine_family          = "POSTGRESQL"
  role_arn               = var.proxy_role_arn
  vpc_subnet_ids         = var.vpc_subnet_ids
  vpc_security_group_ids = var.security_group_ids
  require_tls            = true

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = var.db_secret_arn
  }
}

variable "proxy_role_arn" {
  type    = string
  default = ""
}
variable "db_secret_arn" {
  type    = string
  default = ""
}

# ---------------------------------------------------------------------------
# Redis: broker + result backend + SWR cache (items 34/38/39).
# ---------------------------------------------------------------------------
resource "aws_elasticache_subnet_group" "redis" {
  name       = "manga-redis"
  subnet_ids = var.vpc_subnet_ids
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "manga-redis"
  description                = "Manga broker + cache"
  engine                     = "redis"
  engine_version             = "7.0"
  node_type                  = "cache.r6g.large"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = var.security_group_ids
  port                       = 6379
}

output "database_url" {
  value     = "postgresql+psycopg2://manga:${var.db_password}@${aws_db_proxy.pool.endpoint}:5432/manga"
  sensitive = true
}

output "database_read_url" {
  value     = "postgresql+psycopg2://manga:${var.db_password}@${aws_db_instance.replica.address}:5432/manga"
  sensitive = true
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

/* ============================================================================
   Moneta AI Gateway - 02: tables (generated from gateway/models.py)
   Run as ai_gateway_migrator (or dbo):

   sqlcmd -S <server> -d MonetaAI -U ai_gateway_migrator -C -i 02_schema.sql

   Alternative for dev: `python -m gateway.cli init-db` with the migrator login.
   audit_log is created as a SQL Server 2022 APPEND-ONLY LEDGER table: rows can
   be inserted but never updated or deleted, by anyone (incl. sysadmin), and
   SQL Server keeps a cryptographic digest you can verify with
   sys.sp_verify_database_ledger.
   ========================================================================== */
SET NOCOUNT ON;
GO

IF OBJECT_ID(N'ai_gateway.audit_log') IS NULL
CREATE TABLE ai_gateway.audit_log (
	id INTEGER NOT NULL IDENTITY, 
	ts DATETIME2 NOT NULL, 
	tenant_id INTEGER NULL, 
	user_id INTEGER NULL, 
	client_id NVARCHAR(100) NULL, 
	action NVARCHAR(100) NOT NULL, 
	outcome NVARCHAR(20) NOT NULL, 
	ip NVARCHAR(45) NULL, 
	request_id NVARCHAR(36) NULL, 
	detail NTEXT NOT NULL, 
	prev_hash NVARCHAR(64) NOT NULL, 
	hash NVARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)
WITH (LEDGER = ON (APPEND_ONLY = ON));
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_audit_log_tenant_id')
CREATE INDEX ix_audit_log_tenant_id ON ai_gateway.audit_log (tenant_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_audit_log_ts')
CREATE INDEX ix_audit_log_ts ON ai_gateway.audit_log (ts);
GO

IF OBJECT_ID(N'ai_gateway.oauth_clients') IS NULL
CREATE TABLE ai_gateway.oauth_clients (
	id INTEGER NOT NULL IDENTITY, 
	client_id NVARCHAR(100) NOT NULL, 
	client_name NVARCHAR(200) NOT NULL, 
	redirect_uris NTEXT NOT NULL, 
	client_secret_hash NVARCHAR(255) NULL, 
	client_type NVARCHAR(20) NOT NULL, 
	registered_via NVARCHAR(20) NOT NULL, 
	is_enabled BIT NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (client_id)
);
GO

IF OBJECT_ID(N'ai_gateway.tenants') IS NULL
CREATE TABLE ai_gateway.tenants (
	id INTEGER NOT NULL IDENTITY, 
	name NVARCHAR(200) NOT NULL, 
	is_active BIT NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
GO

IF OBJECT_ID(N'ai_gateway.customers') IS NULL
CREATE TABLE ai_gateway.customers (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id INTEGER NOT NULL, 
	code NVARCHAR(32) NOT NULL, 
	name NVARCHAR(200) NOT NULL, 
	email NVARCHAR(254) NULL, 
	city NVARCHAR(100) NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_customers_tenant_code UNIQUE (tenant_id, code), 
	FOREIGN KEY(tenant_id) REFERENCES ai_gateway.tenants (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_customers_tenant_id')
CREATE INDEX ix_customers_tenant_id ON ai_gateway.customers (tenant_id);
GO

IF OBJECT_ID(N'ai_gateway.products') IS NULL
CREATE TABLE ai_gateway.products (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id INTEGER NOT NULL, 
	sku NVARCHAR(64) NOT NULL, 
	name NVARCHAR(200) NOT NULL, 
	description NVARCHAR(2000) NULL, 
	category NVARCHAR(100) NULL, 
	unit_price NUMERIC(18, 2) NOT NULL, 
	currency NVARCHAR(3) NOT NULL, 
	vat_rate NUMERIC(5, 2) NOT NULL, 
	stock_qty INTEGER NOT NULL, 
	is_active BIT NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	updated_at DATETIME2 NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_products_tenant_sku UNIQUE (tenant_id, sku), 
	FOREIGN KEY(tenant_id) REFERENCES ai_gateway.tenants (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_products_tenant_id')
CREATE INDEX ix_products_tenant_id ON ai_gateway.products (tenant_id);
GO

IF OBJECT_ID(N'ai_gateway.users') IS NULL
CREATE TABLE ai_gateway.users (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id INTEGER NOT NULL, 
	email NVARCHAR(254) NOT NULL, 
	full_name NVARCHAR(200) NOT NULL, 
	password_hash NVARCHAR(255) NOT NULL, 
	role NVARCHAR(20) NOT NULL, 
	is_active BIT NOT NULL, 
	mfa_secret_enc NVARCHAR(255) NULL, 
	failed_logins INTEGER NOT NULL, 
	locked_until DATETIME2 NULL, 
	last_login_at DATETIME2 NULL, 
	created_at DATETIME2 NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES ai_gateway.tenants (id), 
	UNIQUE (email)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_users_tenant_id')
CREATE INDEX ix_users_tenant_id ON ai_gateway.users (tenant_id);
GO

IF OBJECT_ID(N'ai_gateway.admin_sessions') IS NULL
CREATE TABLE ai_gateway.admin_sessions (
	id_hash NVARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	expires_at DATETIME2 NOT NULL, 
	ip NVARCHAR(45) NULL, 
	mfa_pending_enc NVARCHAR(255) NULL, 
	PRIMARY KEY (id_hash), 
	FOREIGN KEY(user_id) REFERENCES ai_gateway.users (id)
);
GO

IF OBJECT_ID(N'ai_gateway.oauth_codes') IS NULL
CREATE TABLE ai_gateway.oauth_codes (
	code_hash NVARCHAR(64) NOT NULL, 
	client_id NVARCHAR(100) NOT NULL, 
	user_id INTEGER NOT NULL, 
	redirect_uri NVARCHAR(500) NOT NULL, 
	code_challenge NVARCHAR(128) NOT NULL, 
	scopes NVARCHAR(500) NOT NULL, 
	resource NVARCHAR(500) NOT NULL, 
	expires_at DATETIME2 NOT NULL, 
	used BIT NOT NULL, 
	PRIMARY KEY (code_hash), 
	FOREIGN KEY(user_id) REFERENCES ai_gateway.users (id)
);
GO

IF OBJECT_ID(N'ai_gateway.oauth_grants') IS NULL
CREATE TABLE ai_gateway.oauth_grants (
	id NVARCHAR(36) NOT NULL, 
	user_id INTEGER NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	client_id NVARCHAR(100) NOT NULL, 
	scopes NVARCHAR(500) NOT NULL, 
	resource NVARCHAR(500) NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	last_used_at DATETIME2 NULL, 
	revoked_at DATETIME2 NULL, 
	revoked_reason NVARCHAR(200) NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES ai_gateway.users (id), 
	FOREIGN KEY(tenant_id) REFERENCES ai_gateway.tenants (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_oauth_grants_user_id')
CREATE INDEX ix_oauth_grants_user_id ON ai_gateway.oauth_grants (user_id);
GO

IF OBJECT_ID(N'ai_gateway.orders') IS NULL
CREATE TABLE ai_gateway.orders (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id INTEGER NOT NULL, 
	order_number NVARCHAR(32) NOT NULL, 
	customer_id INTEGER NOT NULL, 
	status NVARCHAR(20) NOT NULL, 
	currency NVARCHAR(3) NOT NULL, 
	total_net NUMERIC(18, 2) NOT NULL, 
	total_vat NUMERIC(18, 2) NOT NULL, 
	total_gross NUMERIC(18, 2) NOT NULL, 
	notes NVARCHAR(1000) NULL, 
	idempotency_key NVARCHAR(64) NOT NULL, 
	created_by_user_id INTEGER NOT NULL, 
	created_via_client_id NVARCHAR(100) NOT NULL, 
	created_at DATETIME2 NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_orders_tenant_idem UNIQUE (tenant_id, idempotency_key), 
	CONSTRAINT uq_orders_tenant_number UNIQUE (tenant_id, order_number), 
	FOREIGN KEY(tenant_id) REFERENCES ai_gateway.tenants (id), 
	FOREIGN KEY(customer_id) REFERENCES ai_gateway.customers (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES ai_gateway.users (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_orders_created_at')
CREATE INDEX ix_orders_created_at ON ai_gateway.orders (created_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_orders_tenant_id')
CREATE INDEX ix_orders_tenant_id ON ai_gateway.orders (tenant_id);
GO

IF OBJECT_ID(N'ai_gateway.oauth_refresh_tokens') IS NULL
CREATE TABLE ai_gateway.oauth_refresh_tokens (
	token_hash NVARCHAR(64) NOT NULL, 
	grant_id NVARCHAR(36) NOT NULL, 
	expires_at DATETIME2 NOT NULL, 
	rotated_at DATETIME2 NULL, 
	created_at DATETIME2 NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(grant_id) REFERENCES ai_gateway.oauth_grants (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_oauth_refresh_tokens_grant_id')
CREATE INDEX ix_oauth_refresh_tokens_grant_id ON ai_gateway.oauth_refresh_tokens (grant_id);
GO

IF OBJECT_ID(N'ai_gateway.order_lines') IS NULL
CREATE TABLE ai_gateway.order_lines (
	id INTEGER NOT NULL IDENTITY, 
	order_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(18, 2) NOT NULL, 
	vat_rate NUMERIC(5, 2) NOT NULL, 
	line_net NUMERIC(18, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES ai_gateway.orders (id), 
	FOREIGN KEY(product_id) REFERENCES ai_gateway.products (id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_order_lines_order_id')
CREATE INDEX ix_order_lines_order_id ON ai_gateway.order_lines (order_id);
GO

# Snowflake-Databricks Iceberg Integration
# Main Terraform configuration
#
# This deploys the infrastructure needed for Snowflake to read Iceberg tables
# from Databricks Unity Catalog using the PyIceberg + OBJECT_STORE approach.
#
# Components:
# 1. Entra ID Service Principal (for PyIceberg to authenticate to Databricks)
# 2. Snowflake Storage Integration (creates SP for Azure storage access)
# 3. Azure RBAC (grants Snowflake SP access to storage)
#
# Two-Phase Deploy:
# 1. First apply: Set skip_snowflake_sp_lookup = true
# 2. Grant admin consent via the output URL
# 3. Second apply: Set skip_snowflake_sp_lookup = false

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.50"
    }
  }
}

# -----------------------------------------------------------------------------
# VARIABLES
# -----------------------------------------------------------------------------

variable "resource_group_name" {
  description = "Azure resource group name"
  type        = string
}

variable "storage_account_name" {
  description = "Azure storage account name (ADLS Gen2)"
  type        = string
}

variable "storage_container_name" {
  description = "Azure storage container name"
  type        = string
}

variable "storage_base_path" {
  description = "Base path within container (e.g., 'root/')"
  type        = string
  default     = "root/"
}

variable "databricks_workspace_url" {
  description = "Databricks workspace URL (e.g., https://adb-xxx.azuredatabricks.net)"
  type        = string
}

variable "databricks_workspace_id" {
  description = "Databricks workspace resource ID (for Azure auth)"
  type        = string
  default     = null
}

variable "project_name" {
  description = "Project name used for naming resources"
  type        = string
  default     = "snowflake-iceberg"
}

variable "skip_snowflake_sp_lookup" {
  description = "Skip Snowflake SP lookup on first apply (before admin consent)"
  type        = bool
  default     = true
}

variable "create_entra_id_sp" {
  description = "Create Entra ID service principal for PyIceberg authentication"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

# -----------------------------------------------------------------------------
# DATA SOURCES
# -----------------------------------------------------------------------------

data "azurerm_client_config" "current" {}

data "azurerm_subscription" "current" {}

data "azurerm_storage_account" "storage" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
}

# -----------------------------------------------------------------------------
# ENTRA ID SERVICE PRINCIPAL (for PyIceberg → Databricks)
# -----------------------------------------------------------------------------
# This SP is used by PyIceberg running in your network to authenticate
# to Databricks Unity Catalog's Iceberg REST API.

resource "azuread_application" "pyiceberg" {
  count        = var.create_entra_id_sp ? 1 : 0
  display_name = "${var.project_name}-pyiceberg-client"

  tags = ["snowflake-databricks-iceberg", "pyiceberg"]
}

resource "azuread_service_principal" "pyiceberg" {
  count     = var.create_entra_id_sp ? 1 : 0
  client_id = azuread_application.pyiceberg[0].client_id

  tags = ["snowflake-databricks-iceberg", "pyiceberg"]
}

resource "azuread_service_principal_password" "pyiceberg" {
  count                = var.create_entra_id_sp ? 1 : 0
  service_principal_id = azuread_service_principal.pyiceberg[0].id
  display_name         = "PyIceberg client secret"
  end_date_relative    = "8760h" # 1 year
}

# Register the Entra ID SP in Databricks
resource "databricks_service_principal" "pyiceberg" {
  count          = var.create_entra_id_sp ? 1 : 0
  application_id = azuread_application.pyiceberg[0].client_id
  display_name   = "${var.project_name}-pyiceberg-client"
  active         = true
}

# -----------------------------------------------------------------------------
# SNOWFLAKE STORAGE INTEGRATION
# -----------------------------------------------------------------------------
# Creates a storage integration which provisions a multi-tenant Azure AD app
# that Snowflake uses to access Azure storage.

resource "snowflake_storage_integration" "azure" {
  name    = replace("${var.project_name}_azure_storage", "-", "_")
  comment = "Storage integration for Databricks Iceberg tables"
  type    = "EXTERNAL_STAGE"
  enabled = true

  storage_allowed_locations = [
    "azure://${var.storage_account_name}.blob.core.windows.net/${var.storage_container_name}/"
  ]

  storage_provider = "AZURE"
  azure_tenant_id  = data.azurerm_client_config.current.tenant_id
}

# Extract client_id from consent URL
locals {
  snowflake_sp_client_id = replace(
    regex("client_id=[0-9a-f-]{36}", snowflake_storage_integration.azure.azure_consent_url),
    "client_id=",
    ""
  )
}

# Look up Snowflake SP in Azure AD (after admin consent)
data "azuread_service_principal" "snowflake" {
  count     = var.skip_snowflake_sp_lookup ? 0 : 1
  client_id = local.snowflake_sp_client_id

  depends_on = [snowflake_storage_integration.azure]
}

# -----------------------------------------------------------------------------
# AZURE RBAC - Snowflake Storage Access
# -----------------------------------------------------------------------------

resource "azurerm_role_assignment" "snowflake_storage_contributor" {
  count = var.skip_snowflake_sp_lookup ? 0 : 1

  scope                = data.azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azuread_service_principal.snowflake[0].object_id

  description = "Allow Snowflake to read/write to storage for Iceberg tables"
}

resource "azurerm_role_assignment" "snowflake_storage_reader" {
  count = var.skip_snowflake_sp_lookup ? 0 : 1

  scope                = data.azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = data.azuread_service_principal.snowflake[0].object_id

  description = "Allow Snowflake to read storage for Iceberg tables"
}

# -----------------------------------------------------------------------------
# OUTPUTS
# -----------------------------------------------------------------------------

# Entra ID Service Principal (for PyIceberg)
output "pyiceberg_client_id" {
  description = "Entra ID application (client) ID for PyIceberg authentication"
  value       = var.create_entra_id_sp ? azuread_application.pyiceberg[0].client_id : null
}

output "pyiceberg_client_secret" {
  description = "Entra ID client secret for PyIceberg (sensitive)"
  value       = var.create_entra_id_sp ? azuread_service_principal_password.pyiceberg[0].value : null
  sensitive   = true
}

output "pyiceberg_tenant_id" {
  description = "Azure tenant ID for PyIceberg authentication"
  value       = data.azurerm_client_config.current.tenant_id
}

output "databricks_service_principal_id" {
  description = "Databricks service principal ID for PyIceberg"
  value       = var.create_entra_id_sp ? databricks_service_principal.pyiceberg[0].id : null
}

# Snowflake Storage Integration
output "snowflake_storage_integration_name" {
  description = "Snowflake storage integration name"
  value       = snowflake_storage_integration.azure.name
}

output "snowflake_azure_consent_url" {
  description = "URL to grant admin consent for Snowflake storage access"
  value       = snowflake_storage_integration.azure.azure_consent_url
}

output "snowflake_sp_client_id" {
  description = "Snowflake service principal client ID in Azure AD"
  value       = local.snowflake_sp_client_id
}

output "snowflake_sp_object_id" {
  description = "Snowflake service principal object ID (after consent)"
  value       = var.skip_snowflake_sp_lookup ? null : data.azuread_service_principal.snowflake[0].object_id
}

# Storage Configuration
output "storage_account_name" {
  description = "Azure storage account name"
  value       = var.storage_account_name
}

output "storage_container_name" {
  description = "Azure storage container name"
  value       = var.storage_container_name
}

output "storage_base_path" {
  description = "Base path in storage container"
  value       = var.storage_base_path
}

# Generated SQL
output "snowflake_external_volume_sql" {
  description = "SQL to create Snowflake external volume"
  value       = <<-EOT
    -- External Volume for Databricks Iceberg tables
    CREATE EXTERNAL VOLUME ${replace(var.project_name, "-", "_")}_volume
      STORAGE_LOCATIONS = (
        (
          NAME = 'azure_storage'
          STORAGE_PROVIDER = 'AZURE'
          STORAGE_BASE_URL = 'azure://${var.storage_account_name}.blob.core.windows.net/${var.storage_container_name}/${var.storage_base_path}'
          AZURE_TENANT_ID = '${data.azurerm_client_config.current.tenant_id}'
        )
      );

    -- Catalog Integration (REQUIRED for Iceberg tables)
    CREATE CATALOG INTEGRATION ${replace(var.project_name, "-", "_")}_volume_catalog
      CATALOG_SOURCE = OBJECT_STORE
      TABLE_FORMAT = ICEBERG
      ENABLED = TRUE;
  EOT
}

# Environment variables for Python scripts
output "env_file_content" {
  description = "Content for .env file"
  sensitive   = true
  value       = <<-EOT
    # Databricks Configuration
    DATABRICKS_HOST=${var.databricks_workspace_url}

    # Entra ID Service Principal (for PyIceberg)
    AZURE_CLIENT_ID=${var.create_entra_id_sp ? azuread_application.pyiceberg[0].client_id : ""}
    AZURE_CLIENT_SECRET=${var.create_entra_id_sp ? azuread_service_principal_password.pyiceberg[0].value : ""}
    AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}

    # Storage Configuration
    STORAGE_ACCOUNT_NAME=${var.storage_account_name}
    STORAGE_CONTAINER_NAME=${var.storage_container_name}
    STORAGE_BASE_PATH=${var.storage_base_path}

    # Snowflake (add your credentials)
    # SNOWFLAKE_ACCOUNT=
    # SNOWFLAKE_USER=
    # SNOWFLAKE_PASSWORD=
    # SNOWFLAKE_WAREHOUSE=
  EOT
}

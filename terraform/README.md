# Terraform Configuration

Infrastructure-as-code for Snowflake-Databricks Iceberg integration.

## What Gets Created

| Resource | Purpose |
|----------|---------|
| **Entra ID Application** | App registration for PyIceberg authentication |
| **Entra ID Service Principal** | SP for PyIceberg to authenticate to Databricks |
| **Databricks Service Principal** | Registers the Entra ID SP in Databricks |
| **Snowflake Storage Integration** | Creates multi-tenant Azure AD app for storage access |
| **Azure RBAC Assignments** | Grants Snowflake SP access to storage |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TERRAFORM CREATES                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ENTRA ID                          DATABRICKS                          │
│   ════════                          ══════════                          │
│   ┌─────────────────┐               ┌─────────────────┐                │
│   │ App Registration│               │ Service         │                │
│   │ (PyIceberg)     │──────────────►│ Principal       │                │
│   │                 │  Registered   │ (PyIceberg)     │                │
│   │ + SP + Secret   │               │                 │                │
│   └─────────────────┘               └─────────────────┘                │
│                                                                         │
│   SNOWFLAKE                         AZURE STORAGE                       │
│   ═════════                         ═════════════                       │
│   ┌─────────────────┐               ┌─────────────────┐                │
│   │ Storage         │               │ RBAC            │                │
│   │ Integration     │──────────────►│ Assignment      │                │
│   │                 │  Creates SP   │ (Storage Blob   │                │
│   │ (Azure type)    │  in your      │  Data           │                │
│   └─────────────────┘  tenant       │  Contributor)   │                │
│          │                          └─────────────────┘                │
│          │                                                              │
│          ▼                                                              │
│   ┌─────────────────┐                                                  │
│   │ Admin Consent   │◄── Manual step required                          │
│   │ URL             │                                                  │
│   └─────────────────┘                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Two-Phase Deploy

Snowflake storage integrations require admin consent before the service principal
appears in your Azure AD tenant.

### Phase 1: Create Resources

```bash
# Copy example tfvars
cp terraform.tfvars.example terraform.tfvars

# Edit with your values
vim terraform.tfvars

# Ensure skip_snowflake_sp_lookup = true
# This allows the first apply to succeed without the SP existing

terraform init
terraform apply
```

### Grant Admin Consent

```bash
# Get the consent URL
terraform output snowflake_azure_consent_url

# Open the URL in a browser
# Sign in as Azure AD admin
# Click "Accept" to grant consent
```

### Phase 2: Complete Setup

```bash
# Update tfvars
# Set skip_snowflake_sp_lookup = false

terraform apply

# This will:
# - Look up the Snowflake SP in Azure AD
# - Create RBAC role assignments
```

## Provider Configuration

Create a `providers.tf` file:

```hcl
provider "azurerm" {
  features {}
}

provider "azuread" {
  # Uses Azure CLI auth by default
}

provider "snowflake" {
  account  = "ORGNAME-ACCOUNTNAME"
  user     = "your_user"
  password = "your_password"  # Or use env: SNOWFLAKE_PASSWORD
  role     = "ACCOUNTADMIN"
}

provider "databricks" {
  host = var.databricks_workspace_url
  # Uses Azure CLI auth by default
}
```

## Outputs

After successful apply, key outputs include:

```bash
# PyIceberg authentication (for your .env file)
terraform output pyiceberg_client_id
terraform output -raw pyiceberg_client_secret

# Snowflake setup SQL
terraform output snowflake_external_volume_sql

# Generate .env file content
terraform output -raw env_file_content > .env
```

## Using with Python Package

After Terraform deploy:

```bash
# Generate .env from Terraform outputs
terraform output -raw env_file_content > ../.env

# Add Snowflake credentials to .env
echo "SNOWFLAKE_ACCOUNT=your_account" >> ../.env
echo "SNOWFLAKE_USER=your_user" >> ../.env
echo "SNOWFLAKE_PASSWORD=your_password" >> ../.env
echo "SNOWFLAKE_WAREHOUSE=COMPUTE_WH" >> ../.env

# Run the Python package
cd ..
python -m snowflake_databricks_iceberg.external_volume \
  --volume-name databricks_iceberg_volume

python -m snowflake_databricks_iceberg.table_refresher \
  --catalog main \
  --schema my_schema \
  --snowflake-db MY_DB \
  --snowflake-schema MY_SCHEMA \
  --external-volume databricks_iceberg_volume
```

## Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `resource_group_name` | Yes | Azure resource group |
| `storage_account_name` | Yes | ADLS Gen2 storage account |
| `storage_container_name` | Yes | Storage container |
| `storage_base_path` | No | Base path (default: `root/`) |
| `databricks_workspace_url` | Yes | Databricks workspace URL |
| `databricks_workspace_id` | No | Workspace resource ID |
| `project_name` | No | Project name for resource naming |
| `skip_snowflake_sp_lookup` | No | Skip SP lookup on first apply |
| `create_entra_id_sp` | No | Create Entra ID SP for PyIceberg |
| `tags` | No | Resource tags |

"""
Snowflake External Volume for Azure Storage.

Creates and manages Snowflake external volumes pointing to Azure Blob Storage
for direct Iceberg table access.

Reference:
    https://docs.snowflake.com/en/user-guide/tables-iceberg-configure-external-volume-azure
"""

import os
import json
import subprocess
import time
import webbrowser
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

import snowflake.connector
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExternalVolumeConfig:
    """Configuration for an external volume."""

    volume_name: str
    storage_account: str
    container: str
    base_path: str
    tenant_id: str
    storage_base_url: str


class ExternalVolume:
    """
    Create and manage Snowflake external volumes for Azure storage.

    External volumes allow Snowflake to read Iceberg tables directly from
    Azure Blob Storage using the metadata.json file path.

    Example:
        >>> volume = ExternalVolume(
        ...     volume_name="databricks_volume",
        ...     storage_account="myaccount",
        ...     container="mycontainer",
        ...     base_path="root/"
        ... )
        >>> volume.create()
        >>> volume.verify()
    """

    def __init__(
        self,
        volume_name: str,
        storage_account: Optional[str] = None,
        container: Optional[str] = None,
        base_path: str = "root/",
        tenant_id: Optional[str] = None,
        endpoint: str = "dfs",
    ):
        """
        Initialize external volume configuration.

        Args:
            volume_name: Name of the external volume
            storage_account: Azure storage account (auto-detected from Terraform if None)
            container: Azure container name (auto-detected from Terraform if None)
            base_path: Base path within container
            tenant_id: Azure tenant ID (auto-detected from Azure CLI if None)
            endpoint: Azure storage endpoint, "dfs" (ADLS Gen2, default) or "blob".
                Databricks Unity Catalog storage is HNS / ADLS Gen2, and Snowflake
                requires a dfs.core.windows.net STORAGE_BASE_URL for Gen2 interop, so
                "dfs" is the default. See the Snowflake external-volume Azure docs.
        """
        if endpoint not in ("dfs", "blob"):
            raise ValueError(f"endpoint must be 'dfs' or 'blob', got {endpoint!r}")
        self.endpoint = endpoint
        self.volume_name = volume_name
        self.base_path = base_path.rstrip("/") + "/" if base_path else ""

        # Auto-detect configuration
        self.storage_account = storage_account or self._get_terraform_output(
            "storage_account_name"
        )
        self.container = container or self._get_terraform_output("container_name")
        self.tenant_id = tenant_id or self._get_azure_tenant_id()

        # Validate required values
        if not self.storage_account:
            raise ValueError(
                "storage_account required. Provide it or run 'terraform output'."
            )
        if not self.container:
            raise ValueError(
                "container required. Provide it or run 'terraform output'."
            )
        if not self.tenant_id:
            raise ValueError(
                "tenant_id required. Provide it or run 'az account show'."
            )

        # Construct storage URL. Snowflake requires the dfs endpoint for ADLS Gen2
        # (HNS) interop, which is what Databricks Unity Catalog storage uses.
        self.storage_base_url = (
            f"azure://{self.storage_account}.{self.endpoint}.core.windows.net/"
            f"{self.container}/{self.base_path}"
        )

    def _get_terraform_output(self, output_name: str) -> Optional[str]:
        """Get output value from Terraform state."""
        try:
            result = subprocess.run(
                ["terraform", "output", "-raw", output_name],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _get_azure_tenant_id(self) -> Optional[str]:
        """Get Azure tenant ID from CLI or environment."""
        # Try environment first
        tenant_id = os.getenv("AZURE_TENANT_ID")
        if tenant_id:
            return tenant_id

        # Try Azure CLI
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "tenantId", "-o", "tsv"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _get_snowflake_connection(self) -> snowflake.connector.SnowflakeConnection:
        """Get Snowflake connection from environment."""
        required_vars = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
        missing = [v for v in required_vars if not os.getenv(v)]

        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        return snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        )

    def exists(self) -> bool:
        """Check if external volume already exists."""
        conn = self._get_snowflake_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SHOW EXTERNAL VOLUMES")
            volumes = cursor.fetchall()
            volume_names = [str(vol[0]).strip().upper() for vol in volumes]
            return self.volume_name.upper() in volume_names
        finally:
            cursor.close()
            conn.close()

    def create(self, auto_consent: bool = False) -> bool:
        """
        Create the external volume in Snowflake.

        Args:
            auto_consent: If True, wait automatically instead of prompting

        Returns:
            True if successful
        """
        if self.exists():
            print(f"External volume '{self.volume_name}' already exists")
            return True

        conn = self._get_snowflake_connection()
        cursor = conn.cursor()

        try:
            # Create external volume
            create_sql = f"""
            CREATE EXTERNAL VOLUME {self.volume_name}
              STORAGE_LOCATIONS = (
                (
                  NAME = 'azure_storage'
                  STORAGE_PROVIDER = 'AZURE'
                  STORAGE_BASE_URL = '{self.storage_base_url}'
                  AZURE_TENANT_ID = '{self.tenant_id}'
                )
              );
            """

            print(f"Creating external volume: {self.volume_name}")
            print(f"Storage URL: {self.storage_base_url}")

            cursor.execute(create_sql)
            print("External volume created")

            # Get consent URL and app name
            consent_url, app_name = self._get_consent_info(cursor)

            if consent_url:
                self._handle_azure_consent(consent_url, app_name, auto_consent)

            # Create catalog integration
            self._create_catalog_integration(cursor)

            return True

        finally:
            cursor.close()
            conn.close()

    def _get_consent_info(self, cursor) -> Tuple[Optional[str], Optional[str]]:
        """Get Azure consent URL and app name from volume description."""
        cursor.execute(f"DESC EXTERNAL VOLUME {self.volume_name}")
        desc_results = cursor.fetchall()

        consent_url = None
        app_name = None

        for row in desc_results:
            if len(row) >= 4 and row[1] == "STORAGE_LOCATION_1":
                try:
                    storage_config = json.loads(row[3])
                    consent_url = storage_config.get("AZURE_CONSENT_URL")
                    app_name = storage_config.get("AZURE_MULTI_TENANT_APP_NAME")
                    break
                except (json.JSONDecodeError, IndexError):
                    continue

        return consent_url, app_name

    def _handle_azure_consent(
        self,
        consent_url: str,
        app_name: Optional[str],
        auto_consent: bool,
    ):
        """Handle Azure consent flow."""
        print("\n" + "=" * 60)
        print("AZURE IAM SETUP REQUIRED")
        print("=" * 60)

        # Open consent URL
        print(f"\nOpening consent URL in browser...")
        try:
            webbrowser.open(consent_url)
            print("Browser opened - click 'Accept' on the Microsoft permissions page")

            if auto_consent:
                print("Waiting 10 seconds for consent...")
                time.sleep(10)
            else:
                input("\nPress Enter after accepting permissions...")

        except Exception as e:
            print(f"Could not open browser: {e}")
            print(f"Visit manually: {consent_url}")
            if not auto_consent:
                input("\nPress Enter after accepting permissions...")
            else:
                time.sleep(10)

        # Grant storage access
        if app_name:
            self._grant_storage_access(app_name)

    def _grant_storage_access(self, app_name: str):
        """Grant Azure storage access to Snowflake service principal."""
        print("\nGranting storage access...")

        # Wait for Azure to propagate
        time.sleep(5)

        # Find service principal
        sp_id = self._find_service_principal(app_name)
        if not sp_id:
            print(f"Service principal not found: {app_name}")
            print("It may take up to 1 hour to appear. Grant manually:")
            print(f"  az role assignment create \\")
            print(f"    --role 'Storage Blob Data Contributor' \\")
            print(f"    --assignee <sp_object_id> \\")
            print(f"    --scope /subscriptions/.../storageAccounts/{self.storage_account}")
            return

        # Get scope
        subscription_id = self._get_subscription_id()
        resource_group = self._get_resource_group()

        if not subscription_id or not resource_group:
            print("Could not determine Azure subscription/resource group")
            return

        scope = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
            f"providers/Microsoft.Storage/storageAccounts/{self.storage_account}"
        )

        # Create role assignment
        result = subprocess.run(
            [
                "az",
                "role",
                "assignment",
                "create",
                "--role",
                "Storage Blob Data Contributor",
                "--assignee",
                sp_id,
                "--scope",
                scope,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 or "already exists" in result.stderr.lower():
            print("Storage access granted")
        else:
            print(f"Failed to grant access: {result.stderr}")

    def _find_service_principal(self, app_name: str) -> Optional[str]:
        """Find Snowflake service principal by app name."""
        try:
            search_term = app_name.split("_")[0] if "_" in app_name else app_name

            result = subprocess.run(
                [
                    "az",
                    "ad",
                    "sp",
                    "list",
                    "--display-name",
                    search_term,
                    "--query",
                    "[].id",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            sp_ids = result.stdout.strip().split("\n")
            return sp_ids[0] if sp_ids and sp_ids[0] else None

        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _get_subscription_id(self) -> Optional[str]:
        """Get Azure subscription ID."""
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _get_resource_group(self) -> Optional[str]:
        """Get resource group for storage account."""
        try:
            result = subprocess.run(
                [
                    "az",
                    "storage",
                    "account",
                    "show",
                    "--name",
                    self.storage_account,
                    "--query",
                    "resourceGroup",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _create_catalog_integration(self, cursor):
        """Create catalog integration for external volume."""
        integration_name = f"{self.volume_name}_catalog"

        try:
            cursor.execute("SHOW CATALOG INTEGRATIONS")
            integrations = cursor.fetchall()
            names = [str(row[0]).strip().upper() for row in integrations]

            if integration_name.upper() in names:
                print(f"Catalog integration '{integration_name}' already exists")
                return

            cursor.execute(f"""
                CREATE CATALOG INTEGRATION {integration_name}
                  CATALOG_SOURCE = OBJECT_STORE
                  TABLE_FORMAT = ICEBERG
                  ENABLED = TRUE;
            """)
            print(f"Created catalog integration: {integration_name}")

        except Exception as e:
            if "already exists" not in str(e).lower():
                print(f"Error creating catalog integration: {e}")

    def verify(self, max_retries: int = 3, wait_seconds: int = 30) -> bool:
        """
        Verify external volume access.

        Args:
            max_retries: Number of verification attempts
            wait_seconds: Seconds to wait between retries

        Returns:
            True if verification succeeds
        """
        conn = self._get_snowflake_connection()
        cursor = conn.cursor()

        try:
            print(f"Verifying external volume: {self.volume_name}")

            for attempt in range(1, max_retries + 1):
                try:
                    cursor.execute(
                        f"SELECT SYSTEM$VERIFY_EXTERNAL_VOLUME('{self.volume_name}')"
                    )
                    result = cursor.fetchone()

                    if result and "SUCCESS" in str(result[0]).upper():
                        print("Verification successful!")
                        return True
                    else:
                        print(f"Attempt {attempt}/{max_retries}: {result}")

                except Exception as e:
                    print(f"Attempt {attempt}/{max_retries}: {e}")

                if attempt < max_retries:
                    print(f"Waiting {wait_seconds}s before retry...")
                    time.sleep(wait_seconds)

            print("Verification did not succeed after all attempts")
            print("This may be due to Azure role propagation delay (up to 10 minutes)")
            return False

        finally:
            cursor.close()
            conn.close()

    def get_config(self) -> ExternalVolumeConfig:
        """Get the external volume configuration."""
        return ExternalVolumeConfig(
            volume_name=self.volume_name,
            storage_account=self.storage_account,
            container=self.container,
            base_path=self.base_path,
            tenant_id=self.tenant_id,
            storage_base_url=self.storage_base_url,
        )


def main():
    """CLI entry point for external volume management."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Create Snowflake external volume for Azure storage"
    )
    parser.add_argument(
        "--external-volume-name",
        required=True,
        help="Name of the external volume",
    )
    parser.add_argument(
        "--storage-account",
        help="Azure storage account (auto-detected from Terraform)",
    )
    parser.add_argument(
        "--container",
        help="Azure container name (auto-detected from Terraform)",
    )
    parser.add_argument(
        "--storage-base-path",
        default="root/",
        help="Base path within container (default: root/)",
    )
    parser.add_argument(
        "--tenant-id",
        help="Azure tenant ID (auto-detected from Azure CLI)",
    )
    parser.add_argument(
        "--endpoint",
        choices=["dfs", "blob"],
        default="dfs",
        help="Azure storage endpoint: dfs (ADLS Gen2, default) or blob",
    )
    parser.add_argument(
        "--auto-consent",
        action="store_true",
        help="Auto-wait for consent without prompting",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip verification after creation",
    )

    args = parser.parse_args()

    volume = ExternalVolume(
        volume_name=args.external_volume_name,
        storage_account=args.storage_account,
        container=args.container,
        base_path=args.storage_base_path,
        tenant_id=args.tenant_id,
        endpoint=args.endpoint,
    )

    print("=" * 60)
    print("External Volume Configuration")
    print("=" * 60)
    config = volume.get_config()
    print(f"Volume Name:     {config.volume_name}")
    print(f"Storage Account: {config.storage_account}")
    print(f"Container:       {config.container}")
    print(f"Base Path:       {config.base_path}")
    print(f"Tenant ID:       {config.tenant_id}")
    print(f"Storage URL:     {config.storage_base_url}")
    print("=" * 60)

    if volume.create(auto_consent=args.auto_consent):
        if not args.no_verify:
            volume.verify()
        print("\nExternal volume setup complete!")
    else:
        print("\nExternal volume setup failed")
        exit(1)


if __name__ == "__main__":
    main()

"""Tests for IcebergCatalogClient."""

import pytest


class TestIcebergCatalogClient:
    """Tests for the IcebergCatalogClient class."""

    def test_import(self):
        """Test that the client can be imported."""
        from snowflake_databricks_iceberg import IcebergCatalogClient

        assert IcebergCatalogClient is not None

    def test_rest_endpoint_constant(self):
        """Test the REST API endpoint is correct."""
        from snowflake_databricks_iceberg.catalog_client import IcebergCatalogClient

        # Must use hyphen (iceberg-rest), not underscore
        assert "iceberg-rest" in IcebergCatalogClient.ICEBERG_REST_ENDPOINT

    def test_init_requires_workspace_host(self):
        """Test that workspace_host is required."""
        from snowflake_databricks_iceberg import IcebergCatalogClient

        client = IcebergCatalogClient(
            workspace_host="https://test.azuredatabricks.net",
            catalog_name="main",
        )
        assert client.workspace_host == "https://test.azuredatabricks.net"
        assert client.catalog_name == "main"

    def test_workspace_host_trailing_slash_stripped(self):
        """Test that trailing slash is stripped from workspace host."""
        from snowflake_databricks_iceberg import IcebergCatalogClient

        client = IcebergCatalogClient(
            workspace_host="https://test.azuredatabricks.net/",
            catalog_name="main",
        )
        assert client.workspace_host == "https://test.azuredatabricks.net"


class TestTableRefresherPathConversion:
    """Tests for ABFSS path conversion."""

    def test_convert_abfss_path(self):
        """Test converting abfss:// URL to Snowflake path."""
        from snowflake_databricks_iceberg.table_refresher import TableRefresher

        # Create instance (won't connect without env vars)
        class MockRefresher(TableRefresher):
            def __init__(self):
                pass

        refresher = MockRefresher()

        # Test basic conversion
        abfss_url = (
            "abfss://container@account.dfs.core.windows.net/"
            "root/catalog/schema/table/metadata/00001.metadata.json"
        )
        result = refresher.convert_abfss_to_snowflake_path(abfss_url)

        # Should strip root/ prefix
        assert result == "catalog/schema/table/metadata/00001.metadata.json"

    def test_convert_abfss_path_no_root_prefix(self):
        """Test converting abfss:// URL without root/ prefix."""
        from snowflake_databricks_iceberg.table_refresher import TableRefresher

        class MockRefresher(TableRefresher):
            def __init__(self):
                pass

        refresher = MockRefresher()

        abfss_url = (
            "abfss://container@account.dfs.core.windows.net/"
            "catalog/schema/table/metadata/00001.metadata.json"
        )
        result = refresher.convert_abfss_to_snowflake_path(abfss_url)

        assert result == "catalog/schema/table/metadata/00001.metadata.json"

    def test_convert_invalid_url_raises(self):
        """Test that invalid URLs raise ValueError."""
        from snowflake_databricks_iceberg.table_refresher import TableRefresher

        class MockRefresher(TableRefresher):
            def __init__(self):
                pass

        refresher = MockRefresher()

        with pytest.raises(ValueError, match="Invalid abfss URL"):
            refresher.convert_abfss_to_snowflake_path("https://invalid.com/path")


class TestCatalogIntegration:
    """Tests for CatalogIntegration class."""

    def test_import(self):
        """Test that catalog integration can be imported."""
        from snowflake_databricks_iceberg import CatalogIntegration, CatalogSource

        assert CatalogIntegration is not None
        assert CatalogSource.OBJECT_STORE.value == "OBJECT_STORE"
        assert CatalogSource.ICEBERG_REST.value == "ICEBERG_REST"

    def test_generate_object_store_sql(self):
        """Test generating OBJECT_STORE SQL."""
        from snowflake_databricks_iceberg.catalog_integration import CatalogIntegration

        sql = CatalogIntegration.generate_object_store_sql("my_catalog")

        assert "CREATE CATALOG INTEGRATION my_catalog" in sql
        assert "CATALOG_SOURCE = OBJECT_STORE" in sql
        assert "TABLE_FORMAT = ICEBERG" in sql

    def test_generate_rest_sql(self):
        """Test generating ICEBERG_REST SQL."""
        from snowflake_databricks_iceberg.catalog_integration import CatalogIntegration

        sql = CatalogIntegration.generate_rest_sql(
            name="databricks_rest",
            workspace_host="https://test.azuredatabricks.net",
            catalog_name="main",
            schema_name="my_schema",
        )

        assert "CREATE CATALOG INTEGRATION databricks_rest" in sql
        assert "CATALOG_SOURCE = ICEBERG_REST" in sql
        assert "CATALOG_URI = 'https://test.azuredatabricks.net/api/2.1/unity-catalog/iceberg'" in sql
        assert "WAREHOUSE = 'main'" in sql
        assert "CATALOG_NAMESPACE = 'my_schema'" in sql


class TestExternalVolume:
    """Tests for ExternalVolume class."""

    def test_import(self):
        """Test that ExternalVolume can be imported."""
        from snowflake_databricks_iceberg import ExternalVolume

        assert ExternalVolume is not None

    def test_storage_url_format(self):
        """Test that storage URL is formatted correctly."""
        from snowflake_databricks_iceberg.external_volume import ExternalVolume

        # Cannot fully test without env vars, but we can test the URL building
        class MockVolume(ExternalVolume):
            def __init__(self):
                self.storage_account = "testaccount"
                self.container = "testcontainer"
                self.base_path = "root/"
                self.storage_base_url = (
                    f"azure://{self.storage_account}.blob.core.windows.net/"
                    f"{self.container}/{self.base_path}"
                )

        vol = MockVolume()
        expected = "azure://testaccount.blob.core.windows.net/testcontainer/root/"
        assert vol.storage_base_url == expected

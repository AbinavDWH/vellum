from typing import Dict, Any, List
from app.adapters.cloud.base import CloudProviderAdapter


class AzureAdapter(CloudProviderAdapter):
    """Azure implementation — PLANNED (Architecture Ready)."""

    def get_provider_name(self) -> str:
        return "azure"

    def get_local_endpoint(self) -> str:
        return "http://localhost:10000"  # Azurite (Azure Storage Emulator)

    def map_resources(self, universal_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError("Azure adapter not yet implemented in Phase 1.")

    def generate_terraform(self, mapped_resources: List[Dict[str, Any]], environment: str = "local") -> str:
        raise NotImplementedError("Azure adapter not yet implemented in Phase 1.")

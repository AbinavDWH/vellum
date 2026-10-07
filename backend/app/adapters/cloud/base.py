from abc import ABC, abstractmethod
from typing import Dict, Any, List


class CloudProviderAdapter(ABC):
    """Abstract base for cloud providers."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider identifier: 'aws', 'azure', 'gcp'"""
        pass

    @abstractmethod
    def map_resources(self, universal_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map universal IR resources to provider-specific resource definitions."""
        pass

    @abstractmethod
    def generate_terraform(self, mapped_resources: List[Dict[str, Any]], environment: str = "local") -> str:
        """Generate provider-specific Terraform HCL."""
        pass

    @abstractmethod
    def get_local_endpoint(self) -> str:
        """Return local simulation endpoint."""
        pass

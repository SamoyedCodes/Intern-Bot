from abc import ABC, abstractmethod
from typing import Dict, Any, List

class ATSPluginInterface(ABC):
    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Identifier for the ATS (e.g., 'Workday', 'Greenhouse')"""
        pass

    @property
    @abstractmethod
    def domain_matchers(self) -> List[str]:
        """A list of substrings or domains that map a job URL to this plugin."""
        pass

    @abstractmethod
    async def detect_account_existence(self, page: Any, profile: Dict[str, Any]) -> bool:
        """Probes the portal to check if the user already has an account"""
        pass

    @abstractmethod
    async def create_account(self, page: Any, profile: Dict[str, Any]) -> bool:
        """Executes the registration flow and stores credentials"""
        pass

    @abstractmethod
    async def apply_to_job(self, job_url: str, profile: Dict[str, Any], context: Any) -> Any:
        """Navigates the application form and injects profile data"""
        pass

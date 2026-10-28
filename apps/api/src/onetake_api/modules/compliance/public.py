from onetake_api.modules.compliance.domain import ComplianceReport
from onetake_api.modules.compliance.service import ComplianceApplicationService


class CompliancePublicService:
    def __init__(self) -> None:
        self._service = ComplianceApplicationService()

    def report(self, session, *, project_id: str) -> ComplianceReport:
        return self._service.report(session, project_id=project_id)

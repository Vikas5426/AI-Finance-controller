"""
AI Issues Center API Endpoints
Provides the single canonical endpoint for the AI Issues Center report.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.models.ai_issues import AIIssuesReport
from app.services.ai_issues_service import AIIssuesService

router = APIRouter(prefix="/ai-issues", tags=["AI Issues Center"])


@router.get("/report", response_model=AIIssuesReport)
def get_ai_issues_report(
    batch_id: Optional[str] = Query(None, description="Specific batch ID to generate issues report for. If omitted, uses latest active batch."),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> AIIssuesReport:
    """
    Returns the comprehensive, unified AI Issues Center report for the user's organization.
    Ranked strictly by priority:
    1. CRITICAL -> 2. HIGH -> 3. MEDIUM -> 4. LOW
    Within each severity: Highest financial impact -> Lowest financial impact.
    """
    org_id = current_user["org_id"]
    report = AIIssuesService.generate_report(org_id=org_id, batch_id=batch_id)
    return report

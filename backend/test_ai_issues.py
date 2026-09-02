import json
import sys
from app.services.ai_issues_service import AIIssuesService
from app.core.config import settings

def run_tests():
    print(">>> 1. Generating AI Issues Report for DEFAULT_ORG_ID...")
    r = AIIssuesService.generate_report(settings.DEFAULT_ORG_ID)
    
    print("\n=======================================================")
    print("AI ISSUES CENTER REPORT FACT-CHECK VALIDATION")
    print("=======================================================")
    print(f"Batch ID: {r.batch_id}")
    print(f"Overall Health: {r.overall_health}")
    print(f"Audit Chain: {r.audit_integrity} ({r.audit_integrity_detail})")
    print(f"Total Issues: {r.total_issues}")
    print(f"Total Financial Impact: {r.total_financial_impact_formatted}")
    print(f"Critical Count: {r.critical_count} | High Count: {r.high_count} | Medium Count: {r.medium_count} | Low Count: {r.low_count}")
    print(f"Human Review Required: {r.human_review_count}")
    
    assert r.total_issues == len(r.issues), f"Mismatch: total_issues {r.total_issues} vs len(issues) {len(r.issues)}"
    
    print("\n--- DETAILED ISSUE CARDS ---")
    for idx, issue in enumerate(r.issues, 1):
        print(f"\n[Card {idx}] {issue.severity} | {issue.title}")
        print(f"  Financial Impact: {issue.financial_impact_formatted} ({issue.affected_records} records)")
        print(f"  Owner: {issue.owner}")
        print(f"  Next Step: {issue.next_step}")
        print(f"  What Happened: {issue.what_happened}")
        print(f"  Likely Cause: {issue.likely_cause}")
        print(f"  Recommended Action: {issue.recommended_action}")
        if issue.arithmetic_proof:
            print("  Arithmetic Proof:")
            print(f"    Title: {issue.arithmetic_proof.get('title')}")
            for line in issue.arithmetic_proof.get("lines", []):
                print(f"      - {line}")
            print(f"    Explanation: {issue.arithmetic_proof.get('explanation')}")

    print("\n--- SYSTEMIC PATTERNS ---")
    for pat in r.systemic_patterns:
        print(f"[{pat.pattern_id}] {pat.pattern_name} | Impact: {pat.impact_formatted}")
        print(f"  Root Cause: {pat.likely_systemic_cause}")
        print(f"  Remediation: {pat.recommended_remediation} (Owner: {pat.remediation_owner})")

    print("\n--- CONTROLLER'S EXECUTIVE TAKEAWAY ---")
    print(r.controller_takeaway)

    print("\n>>> 2. Testing Empty / Clean Batch Scenario...")
    clean_r = AIIssuesService.generate_report("non-existent-org-empty-batch")
    print(f"Clean Batch Issues: {clean_r.total_issues}")
    print(f"Clean Batch Impact: {clean_r.total_financial_impact_formatted}")
    print(f"Clean Batch Health: {clean_r.overall_health}")
    assert clean_r.total_issues == 0, "Clean batch should have 0 issues"
    assert clean_r.total_financial_impact == 0.0, "Clean batch financial impact should be 0.0"

    print("\n>>> ALL FACT-CHECK & ACCURACY ASSERTIONS PASSED SUCCESSFULLY! <<<\n")

if __name__ == "__main__":
    run_tests()

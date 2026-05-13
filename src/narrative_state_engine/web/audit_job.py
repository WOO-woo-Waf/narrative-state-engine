from __future__ import annotations

import argparse
import json
import os

from narrative_state_engine.domain.audit_assistant import AuditActionService
from narrative_state_engine.storage.audit import build_audit_draft_repository
from narrative_state_engine.storage.repository import build_story_state_repository


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute an audit action draft.")
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--actor", default="author")
    args = parser.parse_args()
    database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("NOVEL_AGENT_DATABASE_URL is required for execute-audit-draft jobs")
    service = AuditActionService(
        state_repository=build_story_state_repository(database_url, auto_init_schema=True),
        audit_repository=build_audit_draft_repository(database_url),
    )
    print(json.dumps(service.execute_draft(args.draft_id, actor=args.actor), ensure_ascii=False))


if __name__ == "__main__":
    main()

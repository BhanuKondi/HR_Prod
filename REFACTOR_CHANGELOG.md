# Refactor Changelog

## Scope
This document summarizes the safe refactors applied to reduce duplication and improve maintainability without changing business behavior.

## New Shared Utilities

### `utils/route_guards.py`
- `require_employee_or_redirect(...)`
- `require_owned_resource_or_redirect(...)`
- `require_assigned_resource_or_redirect(...)`

Purpose:
- Standardize employee-exists checks.
- Standardize ownership checks (employee can only access own records).
- Standardize assignment checks (manager can only access assigned approvals).

### `utils/route_actions.py`
- `execute_db_action(mutator, success_message, after_commit=None)`

Purpose:
- Centralize common pattern:
  - mutate DB state
  - commit
  - rollback on exception
  - flash success/error
  - optional post-commit action (email notifications)

### `utils/workflow_messages.py`
Centralized approval/rejection/payment/closure messages and email subjects/bodies for:
- reimbursements
- loans
- accounts requests

Purpose:
- Keep workflow wording consistent.
- Avoid string duplication across routes.

## New Summary Helpers

### `utils/reimbursement_service.py`
- `summarize_employee_reimbursements(...)`
- `summarize_manager_reimbursements(...)`
- `summarize_account_reimbursements(...)`
- `summarize_admin_reimbursement_reports(...)`

### `utils/loan_service.py`
- `summarize_employee_loans(...)`
- `summarize_manager_loans(...)`
- `summarize_account_loans(...)`

Purpose:
- Centralize dashboard/list summary counters.
- Ensure consistent status counting logic across modules.

## Route Modules Updated

### Reimbursements
- `routes/reimbursements/employee_reimbursements.py`
  - duplicated submission assignment and notify logic consolidated
  - shared employee/ownership guards used
- `routes/reimbursements/manager_reimbursements.py`
  - shared assignment guard used
  - DB action helper used for approve/reject
- `routes/reimbursements/account_reimbursements.py`
  - DB action helper used for approve/reject/mark-paid
  - shared workflow messages used
- `routes/reimbursements/admin_reimbursements.py`
  - shared reimbursement summary helper used

### Loans
- `routes/loans/employee_loans.py`
  - shared employee/ownership guards used
  - shared loan summary helper used
- `routes/loans/manager_loans.py`
  - shared assignment guard used
  - DB action helper used for approve/reject
  - shared workflow messages used
- `routes/loans/account_loans.py`
  - shared loan summary helper used
  - DB action helper used for mark-paid
  - shared workflow messages used
- `routes/admin/admin_loans.py`
  - shared loan summary helper used
  - DB action helper used for approve/reject
  - shared workflow messages used

### Accounts Requests
- `routes/accounts/manager_account_requests.py`
  - shared assignment guard used
- `routes/admin/admin_account_requests.py`
  - DB action helper used for approve/reject/close
  - shared workflow messages used

## Security/Hardening Fixes Included Earlier
- Removed unsafe writes to non-existent user fields in employee edit flow.
- Added app-wide CSRF enforcement for non-API POST requests.
- Added automatic CSRF hidden-field injection via `static/js/main.js`.
- Stopped hardcoded debug mode; now env-driven (`FLASK_DEBUG`).
- Removed committed plaintext SMTP test credentials from `test.py`.
- Made API employee create flow transactional.

## Validation
- `python3 -m py_compile` was used after each refactor slice for syntax validation of touched modules.

## Guidance For Future Changes
- Prefer shared guard helpers over inline ownership/assignment checks.
- Prefer `execute_db_action(...)` for approval actions that mutate DB + send notifications.
- Add new workflow strings to `utils/workflow_messages.py` instead of hardcoding in routes.
- Add/adjust summary logic in service helpers, not in route handlers.

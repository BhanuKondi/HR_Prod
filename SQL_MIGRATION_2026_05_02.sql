-- HRApp Production Migration
-- Date: 2026-05-02
-- Scope: Database schema updates introduced today
-- Notes:
--   1) This script is idempotent (safe to run multiple times).
--   2) Run against database: hr_application
--   3) App-level/template/report changes are not included here because they are code-only.

USE hr_application;

-- =====================================================
-- 1) Salary Revision Workflow Config
-- =====================================================
CREATE TABLE IF NOT EXISTS salary_revision_config (
    id INT NOT NULL AUTO_INCREMENT,
    fixed_approver_user_id INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_salary_revision_config_approver
        FOREIGN KEY (fixed_approver_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================
-- 2) Salary Revision Requests
-- =====================================================
CREATE TABLE IF NOT EXISTS salary_revision_requests (
    id INT NOT NULL AUTO_INCREMENT,
    revision_no VARCHAR(30) NOT NULL,
    employee_id INT NOT NULL,
    requested_by_user_id INT NOT NULL,
    approver_user_id INT NULL,
    effective_from DATE NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    current_salary_json JSON NOT NULL,
    proposed_salary_json JSON NOT NULL,
    approver_comments TEXT NULL,
    submitted_at DATETIME NULL,
    approved_at DATETIME NULL,
    rejected_at DATETIME NULL,
    applied_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_salary_revision_requests_revision_no (revision_no),
    KEY idx_salary_revision_requests_employee_id (employee_id),
    KEY idx_salary_revision_requests_requested_by (requested_by_user_id),
    KEY idx_salary_revision_requests_approver (approver_user_id),
    KEY idx_salary_revision_requests_status (status),
    KEY idx_salary_revision_requests_effective_from (effective_from),
    CONSTRAINT fk_salary_revision_requests_employee
        FOREIGN KEY (employee_id) REFERENCES employees(id),
    CONSTRAINT fk_salary_revision_requests_requested_by
        FOREIGN KEY (requested_by_user_id) REFERENCES users(id),
    CONSTRAINT fk_salary_revision_requests_approver
        FOREIGN KEY (approver_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================
-- 3) Salary Revision Actions (Audit Trail)
-- =====================================================
CREATE TABLE IF NOT EXISTS salary_revision_actions (
    id INT NOT NULL AUTO_INCREMENT,
    salary_revision_request_id INT NOT NULL,
    action_by_user_id INT NOT NULL,
    action_type VARCHAR(30) NOT NULL,
    from_status VARCHAR(30) NULL,
    to_status VARCHAR(30) NOT NULL,
    comments TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_salary_revision_actions_revision_id (salary_revision_request_id),
    KEY idx_salary_revision_actions_action_by (action_by_user_id),
    KEY idx_salary_revision_actions_to_status (to_status),
    CONSTRAINT fk_salary_revision_actions_revision
        FOREIGN KEY (salary_revision_request_id) REFERENCES salary_revision_requests(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_salary_revision_actions_action_by
        FOREIGN KEY (action_by_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================
-- 4) Seed default config row (optional, only if empty)
-- =====================================================
INSERT INTO salary_revision_config (fixed_approver_user_id)
SELECT NULL
WHERE NOT EXISTS (
    SELECT 1 FROM salary_revision_config
);

-- End of migration

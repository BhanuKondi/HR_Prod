INSERT INTO roles (name)
SELECT 'Account Admin'
WHERE NOT EXISTS (
    SELECT 1 FROM roles WHERE LOWER(REPLACE(name, ' ', '_')) = 'account_admin'
);
CREATE TABLE reimbursement_types (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE reimbursement_config (
    id INT PRIMARY KEY AUTO_INCREMENT,
    approver_mode VARCHAR(30) NOT NULL DEFAULT 'reporting_manager',
    fixed_approver_user_id INT NULL,
    allow_partial_approval BOOLEAN NOT NULL DEFAULT TRUE,
    allow_multiple_attachments BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reimbursement_config_fixed_approver
        FOREIGN KEY (fixed_approver_user_id) REFERENCES users(id)
);
CREATE TABLE reimbursement_requests (
    id INT PRIMARY KEY AUTO_INCREMENT,
    request_no VARCHAR(30) NOT NULL UNIQUE,
    employee_id INT NOT NULL,
    reimbursement_type_id INT NOT NULL,
    bill_date DATE NOT NULL,
    submitted_at DATETIME NULL,
    description TEXT NOT NULL,
    requested_amount DECIMAL(12,2) NOT NULL,
    manager_approved_amount DECIMAL(12,2) NULL,
    finance_approved_amount DECIMAL(12,2) NULL,
    final_amount DECIMAL(12,2) NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    manager_approver_user_id INT NULL,
    finance_approver_user_id INT NULL,
    current_assignee_user_id INT NULL,
    manager_comments TEXT NULL,
    finance_comments TEXT NULL,
    payment_reference VARCHAR(100) NULL,
    payment_date DATE NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reimbursement_employee
        FOREIGN KEY (employee_id) REFERENCES employees(id),
    CONSTRAINT fk_reimbursement_type
        FOREIGN KEY (reimbursement_type_id) REFERENCES reimbursement_types(id),
    CONSTRAINT fk_reimbursement_manager_approver
        FOREIGN KEY (manager_approver_user_id) REFERENCES users(id),
    CONSTRAINT fk_reimbursement_finance_approver
        FOREIGN KEY (finance_approver_user_id) REFERENCES users(id),
    CONSTRAINT fk_reimbursement_current_assignee
        FOREIGN KEY (current_assignee_user_id) REFERENCES users(id)
);
CREATE TABLE reimbursement_attachments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    reimbursement_request_id INT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reimbursement_attachment_request
        FOREIGN KEY (reimbursement_request_id) REFERENCES reimbursement_requests(id)
        ON DELETE CASCADE
);
CREATE TABLE reimbursement_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    reimbursement_request_id INT NOT NULL,
    action_by_user_id INT NOT NULL,
    action_type VARCHAR(40) NOT NULL,
    from_status VARCHAR(40) NULL,
    to_status VARCHAR(40) NOT NULL,
    comments TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reimbursement_action_request
        FOREIGN KEY (reimbursement_request_id) REFERENCES reimbursement_requests(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_reimbursement_action_user
        FOREIGN KEY (action_by_user_id) REFERENCES users(id)
);
CREATE TABLE reimbursement_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    reimbursement_request_id INT NOT NULL,
    action_by_user_id INT NOT NULL,
    action_type VARCHAR(40) NOT NULL,
    from_status VARCHAR(40) NULL,
    to_status VARCHAR(40) NOT NULL,
    comments TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reimbursement_action_request
        FOREIGN KEY (reimbursement_request_id) REFERENCES reimbursement_requests(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_reimbursement_action_user
        FOREIGN KEY (action_by_user_id) REFERENCES users(id)
);
INSERT INTO reimbursement_types (name, description, is_active)
SELECT 'Travel', 'Taxi, mileage, and business travel claims', TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_types WHERE LOWER(name) = 'travel');

INSERT INTO reimbursement_types (name, description, is_active)
SELECT 'Food', 'Business meals and approved team expenses', TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_types WHERE LOWER(name) = 'food');

INSERT INTO reimbursement_types (name, description, is_active)
SELECT 'Internet', 'Approved internet or connectivity reimbursement', TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_types WHERE LOWER(name) = 'internet');

INSERT INTO reimbursement_types (name, description, is_active)
SELECT 'Medical', 'Medical reimbursement as per company policy', TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_types WHERE LOWER(name) = 'medical');

INSERT INTO reimbursement_types (name, description, is_active)
SELECT 'Office Supplies', 'Work-related office supply purchases', TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_types WHERE LOWER(name) = 'office supplies');
INSERT INTO reimbursement_config (
    approver_mode,
    fixed_approver_user_id,
    allow_partial_approval,
    allow_multiple_attachments
)
SELECT 'reporting_manager', NULL, TRUE, TRUE
WHERE NOT EXISTS (SELECT 1 FROM reimbursement_config);

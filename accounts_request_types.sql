CREATE TABLE accounts_request_types (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE accounts_request_config (
    id INT PRIMARY KEY AUTO_INCREMENT,
    default_approver_user_id INT NOT NULL,
    allow_partial_approval BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_accounts_request_config_approver
        FOREIGN KEY (default_approver_user_id) REFERENCES users(id)
);
CREATE TABLE accounts_requests (
    id INT PRIMARY KEY AUTO_INCREMENT,
    request_no VARCHAR(30) NOT NULL UNIQUE,
    request_type_id INT NOT NULL,
    created_by_user_id INT NOT NULL,
    approver_user_id INT NOT NULL,
    title VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    requested_amount DECIMAL(12,2) NOT NULL,
    approved_amount DECIMAL(12,2) NULL,
    actual_amount DECIMAL(12,2) NULL,
    payment_mode VARCHAR(30) NULL,
    vendor_name VARCHAR(150) NULL,
    payment_reference VARCHAR(100) NULL,
    payment_date DATE NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    approval_comments TEXT NULL,
    execution_comments TEXT NULL,
    closure_comments TEXT NULL,
    submitted_at DATETIME NULL,
    approved_at DATETIME NULL,
    expense_recorded_at DATETIME NULL,
    closed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_accounts_requests_type
        FOREIGN KEY (request_type_id) REFERENCES accounts_request_types(id),
    CONSTRAINT fk_accounts_requests_created_by
        FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CONSTRAINT fk_accounts_requests_approver
        FOREIGN KEY (approver_user_id) REFERENCES users(id)
);
CREATE TABLE accounts_request_attachments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    accounts_request_id INT NOT NULL,
    attachment_stage VARCHAR(30) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_accounts_request_attachments_request
        FOREIGN KEY (accounts_request_id) REFERENCES accounts_requests(id)
        ON DELETE CASCADE
);
CREATE TABLE accounts_request_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    accounts_request_id INT NOT NULL,
    action_by_user_id INT NOT NULL,
    action_type VARCHAR(40) NOT NULL,
    from_status VARCHAR(40) NULL,
    to_status VARCHAR(40) NOT NULL,
    comments TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_accounts_request_actions_request
        FOREIGN KEY (accounts_request_id) REFERENCES accounts_requests(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_accounts_request_actions_user
        FOREIGN KEY (action_by_user_id) REFERENCES users(id)
);

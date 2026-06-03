-- HR App database changes introduced during the recent improvement pass

-- =====================================================
-- 1. Add profile photo path to users
-- =====================================================
ALTER TABLE users
ADD COLUMN profile_photo_path VARCHAR(255) NULL;


-- =====================================================
-- 2. Ensure required roles exist
-- =====================================================
INSERT INTO roles (name)
SELECT 'Admin'
WHERE NOT EXISTS (
    SELECT 1 FROM roles WHERE LOWER(name) = 'admin'
);

INSERT INTO roles (name)
SELECT 'User'
WHERE NOT EXISTS (
    SELECT 1 FROM roles WHERE LOWER(name) = 'user'
);


-- =====================================================
-- 3. Save uploaded profile photo path
-- =====================================================
UPDATE users
SET profile_photo_path = 'uploads/profile_photos/user_<USER_ID>.<ext>'
WHERE id = <USER_ID>;


-- =====================================================
-- 4. Track successful login time
-- =====================================================
UPDATE users
SET last_login_at = NOW()
WHERE id = <USER_ID>;


-- =====================================================
-- 5. Update user access management fields
-- =====================================================
UPDATE users
SET role_id = <ROLE_ID>,
    is_active = <0_or_1>,
    must_change_password = <0_or_1>
WHERE id = <USER_ID>;


-- =====================================================
-- 6. Admin password reset
-- =====================================================
UPDATE users
SET password_hash = '<HASHED_PASSWORD>',
    must_change_password = 1
WHERE id = <USER_ID>;


-- =====================================================
-- 7. Sync user record when employee is edited
-- =====================================================
UPDATE users
SET email = '<WORK_EMAIL>',
    display_name = '<DISPLAY_NAME>',
    role_id = <ROLE_ID>
WHERE id = <USER_ID>;

UPDATE employees
SET status = '<Active_or_Inactive_or_Terminated>'
WHERE user_id = <USER_ID>;


-- =====================================================
-- 8. Add employee flow
-- =====================================================
INSERT INTO users (
    email,
    password_hash,
    display_name,
    role_id,
    is_active,
    must_change_password,
    created_at
) VALUES (
    '<WORK_EMAIL>',
    '<HASHED_PASSWORD>',
    '<DISPLAY_NAME>',
    <ROLE_ID>,
    1,
    1,
    NOW()
);

INSERT INTO employees (
    emp_code,
    user_id,
    first_name,
    last_name,
    work_email,
    phone,
    department,
    job_title,
    date_of_joining,
    manager_emp_id,
    status,
    created_at,
    updated_at
) VALUES (
    '<EMP_CODE>',
    <USER_ID>,
    '<FIRST_NAME>',
    '<LAST_NAME>',
    '<WORK_EMAIL>',
    '<PHONE>',
    '<DEPARTMENT>',
    '<JOB_TITLE>',
    '<DATE_OF_JOINING>',
    <MANAGER_EMP_ID_OR_NULL>,
    'Active',
    NOW(),
    NOW()
);

INSERT INTO employee_salary (
    employee_id,
    gross_salary,
    basic_percent,
    hra_percent,
    fixed_allowance,
    medical_fixed,
    driver_reimbursement,
    epf_percent,
    total_deductions,
    net_salary
) VALUES (
    <EMPLOYEE_ID>,
    <CTC>,
    <BASIC_PERCENT>,
    <HRA_PERCENT>,
    <FIXED_ALLOWANCE>,
    <MEDICAL_FIXED>,
    <DRIVER_REIMBURSEMENT>,
    <EPF_PERCENT>,
    0,
    <CTC>
);

INSERT INTO employee_account (
    employee_id,
    bank_name,
    account_number,
    ifsc_code,
    account_holder_name
) VALUES (
    <EMPLOYEE_ID>,
    '<BANK_NAME>',
    '<ACCOUNT_NUMBER>',
    '<IFSC_CODE>',
    '<ACCOUNT_HOLDER_NAME>'
);

-- Rollback for 001_add_google_auth_to_users.sql
-- Dropping the columns also removes the UNIQUE constraint/index on google_sub.
ALTER TABLE users
    DROP COLUMN IF EXISTS google_sub,
    DROP COLUMN IF EXISTS is_active;

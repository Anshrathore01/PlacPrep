-- Review and apply locally before testing Supabase-backed application endpoints.
-- This additive mapping preserves every existing numeric users.user_id and FK.
ALTER TABLE users
    ADD COLUMN supabase_user_id CHAR(36) NULL,
    ADD UNIQUE KEY uq_users_supabase_user_id (supabase_user_id);

-- Do not drop this column as a rollback after identities have been linked; doing
-- so would remove the Supabase-to-MySQL identity mapping.

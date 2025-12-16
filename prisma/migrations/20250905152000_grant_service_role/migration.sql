-- Ensure service_role can access required schema objects
grant usage on schema public to service_role;

-- Grant table privileges to service_role
grant select, insert, update, delete on table public.jobs to service_role;

-- Grant sequence usage in case of sequences (future-proof)
grant usage, select on all sequences in schema public to service_role;

-- Optional: default privileges for future tables created by the migration role
-- (affects objects created by the role running this migration)
-- alter default privileges in schema public grant select, insert, update, delete on tables to service_role;
-- alter default privileges in schema public grant usage, select on sequences to service_role;


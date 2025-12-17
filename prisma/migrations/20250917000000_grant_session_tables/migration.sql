-- Grant service_role access to sessions and session_memories tables
-- These were missed in the original migration

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sessions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.session_memories TO service_role;

-- Grant sequence usage for any auto-generated sequences
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

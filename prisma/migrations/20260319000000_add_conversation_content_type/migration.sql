-- Add 'conversation' to the ContentType enum.
-- The Python agent uses 'conversation' for greetings, questions, and general
-- chat, but the original enum only had 'question'. Keep 'question' around for
-- backward compatibility (PostgreSQL does not support dropping enum values).
ALTER TYPE "ContentType" ADD VALUE IF NOT EXISTS 'conversation';

-- NOTE: If any rows have content_type = 'question', run the following manually
-- AFTER this migration has been applied (new enum values cannot be used in DML
-- within the same transaction as ALTER TYPE … ADD VALUE):
--
--   UPDATE "incoming_requests"
--      SET content_type = 'conversation'::"ContentType"
--    WHERE content_type = 'question'::"ContentType";

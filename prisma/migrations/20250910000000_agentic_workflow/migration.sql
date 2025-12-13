-- CreateEnum
CREATE TYPE "ContentType" AS ENUM ('place_name', 'question', 'instagram_link', 'tiktok_link', 'other_link', 'unknown');

-- CreateTable
CREATE TABLE "incoming_requests" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "platform" "Platform" NOT NULL,
    "platform_user_id" TEXT NOT NULL,
    "platform_chat_id" TEXT,
    "message_id" TEXT,
    "raw_content" TEXT,
    "content_type" "ContentType",
    "extracted_data" JSONB,
    "status" "JobStatus" NOT NULL DEFAULT 'queued',
    "error" TEXT,
    "session_id" UUID,
    "metadata" JSONB,
    "raw_payload" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "processed_at" TIMESTAMP(3),

    CONSTRAINT "incoming_requests_pkey" PRIMARY KEY ("id")
);

-- AlterTable
ALTER TABLE "jobs" ADD COLUMN "incoming_request_id" UUID;

-- CreateIndex
CREATE INDEX "idx_incoming_requests_platform_user" ON "incoming_requests"("platform", "platform_user_id");

-- CreateIndex
CREATE INDEX "idx_incoming_requests_status_created" ON "incoming_requests"("status", "created_at");

-- CreateIndex
CREATE INDEX "idx_incoming_requests_content_type" ON "incoming_requests"("content_type");

-- AddForeignKey
ALTER TABLE "incoming_requests" ADD CONSTRAINT "incoming_requests_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "sessions"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_incoming_request_id_fkey" FOREIGN KEY ("incoming_request_id") REFERENCES "incoming_requests"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- Grant permissions to service_role
GRANT ALL ON "incoming_requests" TO service_role;

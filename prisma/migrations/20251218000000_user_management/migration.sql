-- CreateTable: users
CREATE TABLE "users" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "email" TEXT,
    "password_hash" TEXT,
    "display_name" TEXT,
    "subscription_tier" TEXT NOT NULL DEFAULT 'free',
    "daily_request_limit" INTEGER NOT NULL DEFAULT 50,
    "monthly_request_limit" INTEGER NOT NULL DEFAULT 1000,
    "daily_requests_used" INTEGER NOT NULL DEFAULT 0,
    "monthly_requests_used" INTEGER NOT NULL DEFAULT 0,
    "requests_reset_at" TIMESTAMP(3),
    "settings" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable: platform_accounts
CREATE TABLE "platform_accounts" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "platform" "Platform" NOT NULL,
    "platform_user_id" TEXT NOT NULL,
    "platform_username" TEXT,
    "platform_metadata" JSONB,
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "is_verified" BOOLEAN NOT NULL DEFAULT false,
    "linked_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "platform_accounts_pkey" PRIMARY KEY ("id")
);

-- AlterTable: sessions - add user_id column
ALTER TABLE "sessions" ADD COLUMN "user_id" UUID;

-- CreateIndex: unique email on users
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex: unique platform + platform_user_id on platform_accounts
CREATE UNIQUE INDEX "platform_accounts_platform_user_key" ON "platform_accounts"("platform", "platform_user_id");

-- CreateIndex: platform_accounts user lookup
CREATE INDEX "idx_platform_accounts_user" ON "platform_accounts"("user_id");

-- CreateIndex: sessions user lookup
CREATE INDEX "idx_sessions_user" ON "sessions"("user_id");

-- AddForeignKey: platform_accounts -> users
ALTER TABLE "platform_accounts" ADD CONSTRAINT "platform_accounts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey: sessions -> users
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- Grant permissions to service_role
GRANT ALL ON "users" TO service_role;
GRANT ALL ON "platform_accounts" TO service_role;

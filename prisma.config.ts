import "dotenv/config";
import { defineConfig, env } from "prisma/config";

export default defineConfig({
  schema: "prisma/schema.prisma",
  datasource: {
    // DATABASE_URL (pooled) for Prisma Studio and runtime
    url: env("DATABASE_URL"),
    // DIRECT_URL (non-pooled) for migrations to bypass Supavisor/PgBouncer
    // @ts-expect-error directUrl is supported but types may lag behind
    directUrl: env("DIRECT_URL"),
  },
  migrations: {
    path: "prisma/migrations",
  },
});

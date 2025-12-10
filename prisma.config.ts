import { defineConfig } from "prisma/config";
import dotenv from "dotenv";

dotenv.config();

export default defineConfig({
  // DATABASE_URL for Prisma Studio and introspection
  datasource: {
    url: process.env.DATABASE_URL!,
  },
  // DIRECT_URL (non-pooled) for migrations to avoid pgbouncer issues
  migrate: {
    url: process.env.DIRECT_URL,
  },
});

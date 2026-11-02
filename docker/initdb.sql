-- Körs första gången db-containern startar. Huvuddatabasen skapas av POSTGRES_DB;
-- här skapas testdatabasen och extensions i båda (migreringen skapar dem också, idempotent).
CREATE DATABASE vskalkyl_test OWNER vskalkyl;
\connect vskalkyl
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\connect vskalkyl_test
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

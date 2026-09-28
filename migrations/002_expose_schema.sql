-- Expose the order_item schema to the Supabase Data API (PostgREST).
-- Run this in the Supabase SQL Editor AFTER 001_schema.sql.
-- You must ALSO add `order_item` to "Exposed schemas" in
-- Project Settings -> Data API, otherwise the API keeps rejecting it.

GRANT USAGE ON SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA order_item TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON ROUTINES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;

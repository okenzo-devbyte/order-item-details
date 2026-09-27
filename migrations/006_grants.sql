DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON SCHEMA item FROM anon;
        REVOKE ALL ON SCHEMA sales FROM anon;
        REVOKE ALL ON SCHEMA app FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON SCHEMA item FROM authenticated;
        REVOKE ALL ON SCHEMA sales FROM authenticated;
        REVOKE ALL ON SCHEMA app FROM authenticated;
    END IF;
END $$;

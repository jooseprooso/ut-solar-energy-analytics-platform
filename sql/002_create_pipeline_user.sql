do $$
begin
    if not exists (
        select 1
        from pg_roles
        where rolname = 'pipeline_user'
    ) then
        create role pipeline_user
        with login
        password 'REPLACE_WITH_STRONG_PASSWORD';
    end if;
end
$$;

grant connect on database postgres to pipeline_user;

grant usage on schema bronze, silver, gold to pipeline_user;

grant select, insert, update, delete on all tables in schema bronze to pipeline_user;
grant select, insert, update, delete on all tables in schema silver to pipeline_user;
grant select, insert, update, delete on all tables in schema gold to pipeline_user;

grant usage, select, update on all sequences in schema bronze to pipeline_user;
grant usage, select, update on all sequences in schema silver to pipeline_user;
grant usage, select, update on all sequences in schema gold to pipeline_user;

alter default privileges in schema bronze
grant select, insert, update, delete on tables to pipeline_user;
alter default privileges in schema silver
grant select, insert, update, delete on tables to pipeline_user;
alter default privileges in schema gold
grant select, insert, update, delete on tables to pipeline_user;

alter default privileges in schema bronze
grant usage, select, update on sequences to pipeline_user;
alter default privileges in schema silver
grant usage, select, update on sequences to pipeline_user;
alter default privileges in schema gold
grant usage, select, update on sequences to pipeline_user;

# Grafana Operations Runbook

## Eesmärk

See runbook kirjeldab Grafana igapäevaseid operatsioone Hetzneri VM-is: teenuse haldus, tervisekontroll, ligipääs ja tõrkeotsing.

## Stacki haldus

Käivita/käivita uuesti:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml up -d
```

Peata:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml down
```

Seis:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml ps
```

Logid:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml logs grafana --tail=200
```

## Provisioning ja dashboardid

- Datasource provisioning fail: `grafana/provisioning/datasources/supabase-postgres.yml`
- Dashboard provisioning fail: `grafana/provisioning/dashboards/dashboards.yml`
- Dashboardite JSON-failid: `grafana/dashboards/`

Kui muudad provisioning faile või dashboardite JSON-e, käivita teenus uuesti:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml restart grafana
```

## Ligipääsupoliitika

- Grafana port on lokaalne (`127.0.0.1`) ja mõeldud Tailscale võrgu jaoks.
- Väline URL on reverse proxy kaudu: `https://<tailscale-host>/grafana`.
- Admin konto on ainult hooldajatele.
- Tiimiliikmetele loo vajadusel eraldi kasutajad väiksemate õigustega.

Tailscale suunamine proxy peale:

```bash
tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

## Tervisekontroll pärast deployd

1. `docker compose ... ps` näitab, et konteiner on `Up`.
2. Sisselogimine toimib admin kontoga.
3. Datasource test õnnestub.
4. `Solar KPI Overview` dashboard laeb.

## Tõrkeotsing

### 1) Grafana ei käivitu

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml logs grafana --tail=200
```

Kontrolli:
- kas `.env` sisaldab `GRAFANA_ADMIN_*` võtmeid;
- kas hosti port (`GRAFANA_PORT`) pole juba hõivatud.

### 2) Datasource ei ühendu Supabasega

Kontrolli `.env` võtmed:
- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`
- `GRAFANA_SUPABASE_SSLMODE=require`

### 3) Dashboard puudub

- veendu, et JSON fail asub `grafana/dashboards/` kaustas;
- kontrolli provisioning faili teed;
- tee `restart grafana`.

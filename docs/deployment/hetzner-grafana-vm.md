# Hetzner VM Deployment for Grafana

See juhend kirjeldab, kuidas käivitada Grafana olemasolevas Hetzneri VM-is nii, et ligipääs jääb vaikimisi privaatseks (Tailscale kaudu).

## Eeldused

- VM-is on Docker ja Docker Compose olemas.
- Repositoorium on VM-is kloonitud.
- `.env` fail on loodud (`cp .env.example .env`) ja vajalikud väärtused täidetud.
- Tailscale on VM-is töös.

## Nõutud keskkonnamuutujad

Grafana sektsioon `.env` failis:

- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`
- `GRAFANA_PORT` (soovitus: `3000`)
- `GRAFANA_DOMAIN` (valikuline)
- `GRAFANA_ROOT_URL` (soovitus: `https://<tailscale-host>/grafana`)
- `GF_SERVER_SERVE_FROM_SUB_PATH` (soovitus: `true`)
- `GRAFANA_SUPABASE_SSLMODE` (Supabase jaoks `require`)
- `GRAFANA_SUPABASE_DB_SCHEMA` (nt `gold`)

Supabase ühenduse võtmed:

- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`

## Käivitus

Käivita VM-is repositooriumi juurkaustast:

```bash
docker compose --env-file .env -f grafana/docker-compose.grafana.yml config >/tmp/grafana-compose-check.out
docker compose --env-file .env -f grafana/docker-compose.grafana.yml up -d
docker compose --env-file .env -f grafana/docker-compose.grafana.yml ps
```

Käivita reverse proxy (kui pole juba töös):

```bash
docker compose --env-file .env -f proxy/docker-compose.proxy.yml up -d
tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

## Ligipääs

- Grafana port on binditud localhostile (`127.0.0.1:${GRAFANA_PORT}`).
- Tailscale suunatakse reverse proxyle, mis route'ib Grafana tee alla `/grafana`.
- Ava UI: `https://<tailscale-host>/grafana`.

## Minimaalne turvabaas

- Ära ava porti `3000` avalikku internetti.
- Hoia ligipääs ainult Tailscale võrgu kaudu.
- Vaheta `GRAFANA_ADMIN_PASSWORD` tugevaks unikaalseks parooliks.
- Keela anonüümne ligipääs (compose failis juba vaikimisi `false`).
- Sea `.env` ainult omanikule loetavaks:

```bash
chmod 600 .env
```

## Esmane valideerimine

1. Sisselogimine töötab admin kasutajaga.
2. Datasource `Supabase PostgreSQL` on olemas (provisioning).
3. Dashboard `Solar KPI Overview` ilmub kausta `Solar Analytics`.
4. Grafana ei ole avalikust internetist otse kättesaadav.

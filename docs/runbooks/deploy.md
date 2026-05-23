# Deploy Runbook (Hetzner Airflow VM)

## Eesmärk

See runbook kirjeldab hostitud Airflow stacki standardset deploy protsessi ja minimaalseid turvakontrolle, mis peavad olema enne tiimitööd paigas.

## Nõutud keskkonnamuutujad

Serveri `.env` peab sisaldama vähemalt:

- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`
- `VRM_API_TOKEN`
- `VRM_SITE_ID`
- `METEO_LAT`
- `METEO_LON`
- `METEO_TIMEZONE`
- `AIRFLOW_ADMIN_USER`
- `AIRFLOW_ADMIN_PASSWORD`
- `AIRFLOW_ADMIN_EMAIL`
- `AIRFLOW__CORE__AUTH_MANAGER=airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager`
- `AIRFLOW__API__SECRET_KEY` (sama väärtus kõigis Airflow teenustes)
- `AIRFLOW__API_AUTH__JWT_SECRET` (API JWT allkirjastamine)

Märkused:

- `.env` faili ei commitita.
- `AIRFLOW__API__SECRET_KEY` peab olema pikk juhuslik string.

## Standardne deploy järjekord

Käivita serveris repositooriumi juurkaustast:

```bash
git pull --ff-only
docker compose --env-file .env -f airflow/docker-compose.airflow.yml build
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d airflow-init
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d
```

## Deploy-järgne valideerimine

1. Compose konfiguratsioon resolve'ub korrektselt:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml config >/tmp/airflow-compose-check.out
```

2. Põhiteenused on töös:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml ps
```

3. Airflow kasutajahaldus töötab:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-apiserver airflow users list
```

4. DAG run läbib dbt sõltuvuste sammu:
- Triggeri `pipeline_smoke_test` run ja kinnita, et `dbt_deps` on `success`.

5. Airflow API auth sätted on rakendunud:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-apiserver airflow config get-value core auth_manager
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-apiserver airflow config get-value api_auth jwt_secret
```

## dbt failiõiguste guardrail

Kuna konteinerid jooksevad UID `50000` all, peab mountitud `dbt/` kaust olema kirjutatav:

```bash
chown -R 50000:0 dbt
chmod -R u+rwX,g+rwX dbt
```

Kiirkontroll konteinerist:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-scheduler \
  bash -lc 'touch /opt/airflow/project/dbt/.perm_test && rm /opt/airflow/project/dbt/.perm_test'
```

## Minimaalne turvabaas

- Hoia Airflow UI piiratud võrgus (IP allowlist või VPN).
- Soovituslik: Airflow ligipääs ainult Tailscale võrgu kaudu.
- Kasuta avaliku endpointi puhul HTTPS reverse proxy taga.
- Hoia `Admin` roll ainult hooldajatel; inseneridele `Op`/`User`.
- Vaheta default admin parool kohe pärast esmast deployd.
- Sea `.env` fail ainult omanikule loetavaks/kirjutatavaks:
  - `chmod 600 .env`
- Hoia SSH ligipääs võtmetepõhine; keela parooliga sisselogimine.

## Rollback protseduur

Kui deploy ebaõnnestub:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml logs airflow-scheduler --tail=200
docker compose --env-file .env -f airflow/docker-compose.airflow.yml logs airflow-apiserver --tail=200
docker compose --env-file .env -f airflow/docker-compose.airflow.yml restart airflow-scheduler airflow-apiserver airflow-dag-processor
```

Vajadusel mine tagasi eelmisele stabiilsele commitile ja deploy uuesti:

```bash
git checkout <previous-good-commit>
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d --build
```

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
- `AIRFLOW_BASE_URL` (nt `https://<tailscale-host>/airflow`)
- `AIRFLOW__CORE__AUTH_MANAGER=airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager`
- `AIRFLOW__API__SECRET_KEY` (sama väärtus kõigis Airflow teenustes)
- `AIRFLOW__API_AUTH__JWT_SECRET` (API JWT allkirjastamine)
- `GRAFANA_ROOT_URL` (nt `https://<tailscale-host>/grafana`)
- `GF_SERVER_SERVE_FROM_SUB_PATH=true`

Märkused:

- `.env` faili ei commitita.
- `AIRFLOW__API__SECRET_KEY` peab olema pikk juhuslik string.

## Standardne deploy järjekord

Käivita serveris repositooriumi juurkaustast:

```bash
git pull --ff-only
bash scripts/deploy/prepare_airflow_dirs.sh
docker compose --env-file .env -f airflow/docker-compose.airflow.yml build
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d airflow-init
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d
docker compose --env-file .env -f grafana/docker-compose.grafana.yml up -d
docker compose --env-file .env -f proxy/docker-compose.proxy.yml up -d
tailscale serve --bg http://127.0.0.1:8088
```

## GitHub Actions manual deploy

Repo sisaldab manual deploy workflow'd:
- `.github/workflows/deploy_hetzner.yml`

Workflow trigger:
- GitHub -> `Actions` -> `deploy_hetzner` -> `Run workflow`
- `deploy_ref`: hoia `main`
- `run_airflow_init`: kasuta `true` ainult siis, kui on vaja init samm uuesti käivitada

Nõutud GitHub Secrets:
- `HETZNER_SSH_HOST`
- `HETZNER_SSH_USER`
- `HETZNER_SSH_PRIVATE_KEY`
- `HETZNER_DEPLOY_PATH`

Workflow teeb serveris:
1. `git checkout -f main && git reset --hard origin/main && git clean -fd`
2. `bash scripts/deploy/prepare_airflow_dirs.sh`
3. Airflow stack build + `up -d`
4. Grafana stack `up -d`
5. Proxy stack `up -d`
6. `tailscale serve --bg http://127.0.0.1:8088`

## Deploy-järgne valideerimine

1. Compose konfiguratsioon resolve'ub korrektselt:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml config >/tmp/airflow-compose-check.out
```

2. Põhiteenused on töös:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml ps
docker compose --env-file .env -f grafana/docker-compose.grafana.yml ps
docker compose --env-file .env -f proxy/docker-compose.proxy.yml ps
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

6. Tailscale route suunab õigesse stacki:

```bash
tailscale serve status
```

Kontrolli URL-id:
- `https://<tailscale-host>/` (landing page)
- `https://<tailscale-host>/airflow`
- `https://<tailscale-host>/grafana`

## Airflow/dbt failiõiguste guardrail

Kuna konteinerid jooksevad UID `50000` all, peavad mountitud kaustad olema kirjutatavad.
Eelistatud viis on kasutada deploy skripti (käivita deploy-userina, mitte rootina):

```bash
bash scripts/deploy/prepare_airflow_dirs.sh
```

Skript seab õigused nii:
- `airflow/logs` -> `50000:0` (Airflow saab logisid kirjutada)
- `airflow/dags`, `airflow/plugins` -> deploy-user (et `git pull` ei läheks katki)
- `dbt` -> deploy-user + group `0` (`g+rwX`), et dbt runtime saaks kirjutada `dbt/logs` ja `dbt_packages`

Kiirkontroll konteinerist:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-scheduler \
  bash -lc 'touch /opt/airflow/logs/.perm_test && rm /opt/airflow/logs/.perm_test'
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-scheduler \
  bash -lc 'touch /opt/airflow/project/dbt/.perm_test && rm /opt/airflow/project/dbt/.perm_test'
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-scheduler \
  bash -lc 'mkdir -p /opt/airflow/project/dbt/logs && touch /opt/airflow/project/dbt/logs/.perm_test && rm /opt/airflow/project/dbt/logs/.perm_test'
```

## Minimaalne turvabaas

- Hoia Airflow UI piiratud võrgus (IP allowlist või VPN).
- Soovituslik: ligipääs ainult Tailscale võrgu kaudu reverse proxy kaudu.
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

Kui ebaõnnestumine tuli GitHub Actions workflow's:
1. Ava ebaõnnestunud `deploy_hetzner` run.
2. Vaata, milline serverikäsk kukkus läbi.
3. Paranda põhjus PR-iga ja käivita workflow uuesti.

Vajadusel mine tagasi eelmisele stabiilsele commitile ja deploy uuesti:

```bash
git checkout <previous-good-commit>
docker compose --env-file .env -f airflow/docker-compose.airflow.yml up -d --build
```

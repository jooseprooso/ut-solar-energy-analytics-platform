# Off-Grid Päikesejaama Analüütika Platvorm

Off-grid paigaldise telemeetria ja ilmaprognoosi analüütikaplatvorm.

## Äriküsimus

Kuidas mõjutavad ilmastikutingimused off-grid paigaldise energiatootmist ning kui
tapselt on voimalik prognoosida jargmise paeva paikeseenergia tootmist?

## Võtmemõõdikud

- Täpsustamisel

## Tehnoloogiavirn

- Replikatsioon: Python
- Transformatsioon + andmekvaliteet: dbt Core
- Andmeladu: Supabase (Postgres)
- Orkestreerimine: Airflow 3 (peamine scheduler)
- CI kontrollid: GitHub Actions (manual + quality gates)
- Näidikulaud: Grafana Cloud
- Prognoos: Pythoni töö

## Repositooriumi arhitektuur

```text
├─ .github/workflows/
├─ airflow/
│  ├─ dags/
│  ├─ docker/
│  ├─ scripts/
│  └─ docker-compose.airflow.yml
├─ Dockerfile
├─ dbt/
│  ├─ models/
│  │  ├─ silver/
│  │  └─ gold/
│  ├─ dbt_project.yml
│  └─ profiles.yml
├─ docker-compose.yml
├─ docs/
│  ├─ deployment/
│  └─ runbooks/
├─ sql/
├─ tests/
├─ src/
│  ├─ ingest/
│  └─ forecast/
├─ .env.example
├─ requirements.txt
└─ requirements-dev.txt
```

## Kohalikus masinas käivitamine

1. Loo `.env` fail `.env.example` põhjal.
2. Ehita konteiner:
   - `docker compose build`
3. Kontrolli dbt paigaldust konteineris:
   - `docker compose run --rm dev dbt --version`
4. Kontrolli ühendust Supabase'iga:
   - `docker compose run --rm dev dbt debug`
5. Kaivita Python skript konteineris (naide):
   - `docker compose run --rm dev python --version`

## Airflow 3 käivitamine

1. Airflow metadata ja admin kasutaja initsialiseerimine:
   - `docker compose -f airflow/docker-compose.airflow.yml up airflow-init`
2. Airflow stack käivitamine:
   - `docker compose -f airflow/docker-compose.airflow.yml up -d`
3. Airflow UI:
   - `http://localhost:8080`
4. Connectionid/variables bootstrap:
   - `docker compose -f airflow/docker-compose.airflow.yml run --rm airflow-apiserver bash /opt/airflow/project/airflow/scripts/bootstrap_connections.sh`

## Kvaliteediväravad (TDD)

- Lint:
  - `ruff check .`
- Testid:
  - `pytest`
- CI kvaliteediväravad on `.github/workflows/ci_quality.yml`.

## Orkestreerimise poliitika

- Airflow on peamine scheduler.
- GitHub workflow failid `hourly_pipeline` ja `daily_db_check` on alles ainult manual check/CI eesmärgil.
- Automaatne cron-scheduling on GitHub Actionsis välja lülitatud.
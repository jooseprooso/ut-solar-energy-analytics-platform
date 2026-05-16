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
- Orkestreerimine: GitHub Actions (cron)
- Näidikulaud: Grafana Cloud
- Prognoos: Pythoni töö

## Repositooriumi arhitektuur

```text
├─ .github/workflows/
├─ dbt/
│  ├─ models/
│  │  ├─ silver/
│  │  └─ gold/
│  ├─ dbt_project.yml
│  └─ profiles.yml
├─ docs/
├─ sql/
├─ src/
│  ├─ ingest/
│  └─ forecast/
├─ .env.example
└─ requirements.txt
```

## Kohalikus masinas käivitamine

1. Loo virtuaalkeskkond:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Paigalda sõltuvused:
   - `pip install -r requirements.txt`
3. Loo `.env` fail `.env.example` põhjal.
4. Kontrolli dbt paigaldust:
   - `dbt --version`
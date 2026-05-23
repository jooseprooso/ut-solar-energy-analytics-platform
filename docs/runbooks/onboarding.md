# Tiimi Onboarding Runbook

## Eesmärk

See runbook aitab onboardida kaks andmeinseneri nii, et nad saaksid:

- teha arendust repositooriumis (branch + PR),
- kasutada hostitud Airflow UI-d,
- valideerida esimese eduka DAG jooksu.

## Eeldused

- Inseneril on GitHubi konto.
- Insenerile on antud repositooriumis `Write` õigus.
- Inseneril on VPN/IP ligipääs Airflow hosti (või muu lubatud võrgutee).
- Tiimijuhil on Airflow admin ligipääs.

## 1) Repositooriumi ligipääs ja lokaalne setup

1. Lisa insener GitHubis collaboratorina või tiimi liikmena `Write` õigusega.
2. Insener kloonib repositooriumi ja loob isikliku feature branchi:
   - `git checkout -b feat/<lyhike-teema>`
3. Insener kopeerib `.env.example` -> `.env` ainult lokaalseks arenduseks.
4. Insener kontrollib lokaalsed kvaliteediväravad:
   - `ruff check .`
   - `pytest`

## 2) Airflow kasutaja loomine

### Rollipoliitika

- Hoia `Admin` roll ainult hooldajatel.
- Anna inseneridele vaikimisi `Op` roll.
- Kasuta ainult isiklikke kontosid (mitte jagatud kasutajaid).

### Kasutaja loomine

Käivita serveris repositooriumi juurkaustast:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-apiserver \
  airflow users create \
    --username engineer1 \
    --password 'temporary-strong-password' \
    --firstname Engineer \
    --lastname One \
    --role Op \
    --email engineer1@example.com
```

Olemasolevate kasutajate nimekiri:

```bash
docker compose --env-file .env -f airflow/docker-compose.airflow.yml exec airflow-apiserver airflow users list
```

## 3) Esimese päeva valideerimine

Iga insener kinnitab:

1. Saab Airflow UI-sse sisse logida.
2. Näeb DAG-i `solar_pipeline_main`.
3. Saab teha manual triggeri.
4. Näeb task logisid `validate_runtime_config`, `dbt_deps` ja `dbt_run`.
5. Kinnitab, et run jõuab `success` olekusse.

## 4) PR töökorraldus

- Otse `main` branchi ei pushita.
- PR avatakse isiklikust branchist.
- Vähemalt üks reviewer peab kinnitama.
- CI kontrollid peavad enne merge'i läbima.

## 5) Onboardingu valmisoleku checklist

- [ ] GitHub ligipääs on kinnitatud.
- [ ] Airflow kasutaja on loodud ja testitud.
- [ ] Esimene manual DAG run on edukas.
- [ ] Insener on avanud vähemalt ühe PR-i.
- [ ] Insener on läbi vaadanud `docs/runbooks/airflow-operations.md`.

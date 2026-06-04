from pathlib import Path


def test_solar_analytics_dag_contract() -> None:
    dag_file = Path("airflow/dags/solar_analytics_pipeline.py")
    assert dag_file.exists(), "Production DAG file must exist"

    source = dag_file.read_text(encoding="utf-8")

    assert 'dag_id="solar_analytics_hourly"' in source
    assert 'schedule="@hourly"' in source

    for task_id in [
        "validate_runtime_config",
        "ingest_vrm",
        "ingest_meteo",
        "dbt_deps",
        "dbt_run",
        "dbt_test",
        "forecast",
        "dbt_run_forecast_marts",
    ]:
        assert f'task_id="{task_id}"' in source

    assert "[ingest_vrm, ingest_meteo]" in source
    assert ">> forecast" in source
    assert ">> dbt_run_forecast_marts" in source

    assert "BRONZE_TABLE_PREFIX" not in source, "Prod DAG must not use smoke test prefix"

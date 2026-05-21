from pathlib import Path


def test_solar_pipeline_dag_contract() -> None:
    dag_file = Path("airflow/dags/solar_pipeline_main.py")
    assert dag_file.exists(), "Main Airflow DAG file must exist"

    source = dag_file.read_text(encoding="utf-8")

    assert 'dag_id="solar_pipeline_main"' in source
    assert 'schedule="@hourly"' in source

    for task_id in [
        "validate_runtime_config",
        "ingest_vrm",
        "ingest_meteo",
        "dbt_deps",
        "dbt_run",
        "dbt_test",
        "forecast",
    ]:
        assert f'task_id="{task_id}"' in source

    assert "validate_runtime_config >> [ingest_vrm, ingest_meteo]" in source
    assert "[ingest_vrm, ingest_meteo] >> dbt_deps >> dbt_run >> dbt_test >> forecast" in source

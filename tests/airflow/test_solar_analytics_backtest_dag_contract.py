from pathlib import Path


def test_solar_analytics_backtest_dag_contract() -> None:
    dag_file = Path("airflow/dags/solar_analytics_backtest_pipeline.py")
    assert dag_file.exists(), "Backtest DAG file must exist"

    source = dag_file.read_text(encoding="utf-8")

    assert 'dag_id="solar_analytics_backtest_daily"' in source
    assert 'schedule="@daily"' in source

    for task_id in [
        "validate_runtime_config",
        "forecast",
        "dbt_run_forecast_marts",
    ]:
        assert f'task_id="{task_id}"' in source

    assert "--mode backtest" in source
    assert ">> forecast >> dbt_run_forecast_marts" in source

    assert "BRONZE_TABLE_PREFIX" not in source, "Prod DAG must not use smoke test prefix"

"""One ingest DAG per source: download -> raw -> staging -> event_activity -> metadata -> quality checks."""
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from texa_etl.run import PIPELINE, SOURCES, STEPS, load_fx_rates

for source_id in SOURCES:
    with DAG(
        dag_id=f"ingest_{source_id}",
        start_date=datetime(2026, 1, 1),
        schedule=None,  # ponytail: static Kaggle dumps, trigger by hand; set a schedule when a live source arrives
        catchup=False,
        tags=["texa", "ingest"],
        doc_md=SOURCES[source_id]["description"],
    ) as dag:
        previous = None
        for step in PIPELINE:
            task = PythonOperator(task_id=step, python_callable=STEPS[step], op_args=[source_id])
            if previous:
                previous >> task
            previous = task
    globals()[dag.dag_id] = dag

with DAG(
    dag_id="ingest_fx_rates",
    start_date=datetime(2026, 1, 1),
    schedule=None,  # run once before the store DAGs so revenue_usd can be filled
    catchup=False,
    tags=["texa", "ingest"],
    doc_md="Daily exchange rates (FRED). Fills analytics.fx_rates; store loads convert revenue to USD from it.",
) as fx_dag:
    PythonOperator(task_id="load_fx_rates", python_callable=load_fx_rates)

FROM apache/airflow:3.0.2-python3.11

COPY airflow/docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim
WORKDIR /opt/texa
RUN pip install --no-cache-dir "psycopg[binary]==3.2.*"
COPY . /opt/texa/pipeline
ENV PYTHONPATH=/opt/texa/pipeline
CMD ["python", "-m", "texa_etl.run"]

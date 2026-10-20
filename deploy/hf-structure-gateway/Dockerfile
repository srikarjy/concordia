FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock.txt
COPY src /app/src
COPY app.py domain.json /app/
RUN useradd --create-home --uid 10001 concordia && mkdir /app/state && chown concordia /app/state
USER concordia
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--no-access-log"]

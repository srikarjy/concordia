FROM python:3.13-slim

ARG THERMOMPNN_COMMIT=370f76ec
ARG THERMOMPNN_WEIGHTS_SHA256=af449118ccfb4e34971d802321907ed82a8a035ae80f055bf8fc56009a4a838a

WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/Kuhlman-Lab/ThermoMPNN.git /opt/ThermoMPNN \
    && cd /opt/ThermoMPNN \
    && git checkout "${THERMOMPNN_COMMIT}" \
    && test -f models/thermoMPNN_default.pt \
    && echo "${THERMOMPNN_WEIGHTS_SHA256}  models/thermoMPNN_default.pt" | sha256sum -c -

COPY src ./src
COPY data/manifests/tsuboyama_rule2_manifest_v3.json ./data/manifests/tsuboyama_rule2_manifest_v3.json
COPY data/processed/tsuboyama_v2_230420_normalized.csv ./data/processed/tsuboyama_v2_230420_normalized.csv
COPY data/processed/tsuboyama_esm2_site_embeddings.parquet ./data/processed/tsuboyama_esm2_site_embeddings.parquet
COPY data/processed/tsuboyama_ensemble_artifacts.joblib ./data/processed/tsuboyama_ensemble_artifacts.joblib
COPY data/processed/tsuboyama_production_ranker.json ./data/processed/tsuboyama_production_ranker.json
COPY data/processed/tsuboyama_uncertainty_metrics.json ./data/processed/tsuboyama_uncertainty_metrics.json
COPY data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb ./data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb
COPY app.py ./app.py

RUN python -c "import Bio, concordia.stability.measured; print('runtime imports OK')" \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin concordia \
    && mkdir -p /app/.concordia \
    && chown -R concordia:concordia /app /opt/ThermoMPNN
USER concordia
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

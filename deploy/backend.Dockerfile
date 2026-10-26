FROM python:3.11-slim-bookworm

ARG TORCH_VERSION=2.13.0
ARG TORCHVISION_VERSION=0.28.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HOME=/models/huggingface \
    EASYOCR_MODULE_PATH=/models/easyocr

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY ml/requirements.txt /tmp/ml-requirements.txt
COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY constraints.txt /tmp/constraints.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
       --index-url https://download.pytorch.org/whl/cpu \
       "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
    && python -m pip install --no-cache-dir "setuptools==84.1.0" \
    && python -m pip install --no-cache-dir \
       -c /tmp/constraints.txt \
       -r /tmp/ml-requirements.txt -r /tmp/backend-requirements.txt

# Runtime OCR uses this explicit directory, rather than EasyOCR's default /model
# subdirectory. Readers verify the upstream checksums while downloading all
# detector/recognizer weights during the build, before the network is removed.
RUN python -c "import os; import easyocr; model_dir = os.environ['EASYOCR_MODULE_PATH']; [easyocr.Reader(languages, gpu=False, detect_network='craft', recog_network=recognizer, model_storage_directory=model_dir, verbose=False) for languages, recognizer in [(['ko', 'en'], 'korean_g2'), (['en'], 'english_g2')]]"

COPY ml/src /app/ml/src
COPY backend /app/backend
COPY shared /app/shared
COPY scripts/check_backend_image.py /app/scripts/check_backend_image.py

RUN useradd --create-home --uid 10001 marklens \
    && mkdir -p /data /state /models/huggingface \
    && chown -R marklens:marklens /app /state /models

USER marklens

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

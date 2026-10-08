FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY prompt_builder ./prompt_builder
RUN pip install --no-cache-dir . && useradd -r -u 10001 pb
USER pb
ENV PB_HOST=0.0.0.0 PB_PORT=7810 PB_ALLOWED_HOSTS=.*
EXPOSE 7810
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7810/healthz',timeout=3).status==200 else 1)"
CMD ["prompt-builder"]

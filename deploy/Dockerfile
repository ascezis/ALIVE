FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALIVE_DATABASE=/data/lfk.sqlite3

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/requirements.txt \
    && install -d -o 10001 -g 10001 /data

COPY backend/app.py backend/import_lfk.py backend/report_pdf.py /app/backend/
COPY backend/report_fonts/ /app/backend/report_fonts/
COPY src/lfk-spec.json /app/src/lfk-spec.json
COPY miniapp/dist/ /app/miniapp/dist/

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=4s --start-period=5s \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/', timeout=3).close()"]

CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers", "--no-access-log"]

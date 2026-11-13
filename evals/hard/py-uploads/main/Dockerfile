FROM python:3.11-slim
WORKDIR /srv
COPY . .
RUN pip install --no-cache-dir .
ENV STORAGE_ROOT=/data/assets
CMD ["gunicorn", "-w", "4", "app:create_app()"]

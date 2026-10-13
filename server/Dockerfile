FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fg_server fg_server
RUN useradd --uid 10001 --no-create-home app
USER 10001
ENV FG_BIND=0.0.0.0
CMD ["python", "-m", "fg_server", "serve"]

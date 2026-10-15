FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY violet ./violet
ENV VIOLET_DATA_DIR=/data
VOLUME /data
CMD ["python", "-m", "violet"]

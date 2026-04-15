FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app/src /app
COPY .env /app/.env

EXPOSE 5000

CMD ["python", "app.py"]
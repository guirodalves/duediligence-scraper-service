FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

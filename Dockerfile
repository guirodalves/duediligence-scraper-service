FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

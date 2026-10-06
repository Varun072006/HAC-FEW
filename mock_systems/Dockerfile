FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY mock_systems/ /app/mock_systems/

EXPOSE 8001

CMD ["uvicorn", "mock_systems.main:app", "--host", "0.0.0.0", "--port", "8001"]

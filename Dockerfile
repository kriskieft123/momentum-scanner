FROM python:3.11-slim
WORKDIR /app
COPY momentum_server.py .
EXPOSE 8765
CMD ["python3", "momentum_server.py"]

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY guides ./guides
RUN pip install --no-cache-dir . 
EXPOSE 9400
CMD ["edp8-board"]

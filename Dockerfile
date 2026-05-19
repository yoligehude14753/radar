FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    gcc libpq-dev curl git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

# 复制源码
COPY src/ src/
COPY scripts/ scripts/

# 创建必要目录
RUN mkdir -p outputs logs data

EXPOSE 7090

CMD ["radar", "serve"]

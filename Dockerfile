# 合并成 monorepo 之后，代码全在本仓里，镜像**不再需要挂载外部目录**。
# 唯一仍然进不去的是索引（.indexes/ 96MB，要用真 embedding 现建）—— 它挂进来。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY packages/ ./packages/
COPY apps/ ./apps/

ENV PYTHONPATH=/app/packages/ragv1:/app/packages/csagent:/app/apps/api
ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "apps/api/scripts/serve.py"]

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# pyproject.toml 의 고정 버전 의존성만 설치한다(앱 코드는 compose 가 마운트).
COPY pyproject.toml .
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; print('\n'.join(p['dependencies'] + p['optional-dependencies']['dev']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .

EXPOSE 8210
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8210", "--reload"]

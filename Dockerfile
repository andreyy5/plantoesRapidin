FROM python:3.12-slim
WORKDIR /app
# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
 build-essential \
 && rm -rf /var/lib/apt/lists/*
# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copia o projeto
COPY . .
# Coleta arquivos estáticos
RUN python manage.py collectstatic --noinput
# Porta padrão
EXPOSE 5002
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
ENTRYPOINT ["sh", "entrypoint.sh"]
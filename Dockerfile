FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 10001 --create-home bot && mkdir /app/data && chown bot:bot /app/data
COPY --chown=bot:bot bot /app/bot
USER bot
CMD ["python", "-m", "bot.main"]

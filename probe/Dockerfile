FROM python:3.12-slim
WORKDIR /app
COPY probe /app/probe
ENV PORT=8080
EXPOSE 8080
CMD ["python3", "-m", "probe.jobs.job", "serve"]

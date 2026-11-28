FROM python:3.12-slim
WORKDIR /app
COPY iuk_relay.py .
ENV HOST=0.0.0.0 PORT=8787 DATA_DIR=/data TRUST_PROXY=1
VOLUME /data
EXPOSE 8787
USER 10001
CMD ["python", "iuk_relay.py"]

FROM python:3.11-slim

WORKDIR /app

# Set PYTHONPATH so all imports resolve correctly
ENV PYTHONPATH=/app

RUN pip install --no-cache-dir \
    streamlit==1.35.0 \
    streamlit-autorefresh==1.0.1 \
    requests==2.31.0 \
    pandas==2.2.0 \
    plotly==5.22.0 \
    psycopg2-binary==2.9.9 \
    pydantic==2.7.0 \
    pydantic-settings==2.2.0 \
    python-dotenv==1.0.0 \
    fastapi==0.110.0 \
    uvicorn==0.29.0

# Copy as proper packages so imports work
COPY token_optimise/ ./token_optimise/
COPY src/ ./src/

RUN mkdir -p /root/.streamlit
RUN printf '[server]\nport = 7738\naddress = "0.0.0.0"\nheadless = true\n\n[browser]\ngatherUsageStats = false\n' \
    > /root/.streamlit/config.toml

EXPOSE 7737
EXPOSE 7738

CMD ["python", "src/mcp/dash_api.py"]
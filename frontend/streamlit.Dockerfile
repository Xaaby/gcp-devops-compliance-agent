FROM python:3.11-slim

WORKDIR /app

COPY streamlit-requirements.txt .
RUN pip install --no-cache-dir -r streamlit-requirements.txt

COPY streamlit_app.py .

EXPOSE 8080

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]

FROM python:3.12
WORKDIR /app
COPY . /app
RUN pip install .
RUN python run.py setup
EXPOSE 8000
CMD ["python", "run.py", "serve", "host=0.0.0.0", "port=8000"]

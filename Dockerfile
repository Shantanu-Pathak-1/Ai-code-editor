# Base image
FROM python:3.9

# Working directory set karna
WORKDIR /code

# Requirements file copy aur install karna
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Humara app code copy karna
COPY . .

# Hugging face ke port 7860 par FastAPI ko run karna
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
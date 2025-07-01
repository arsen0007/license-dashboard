# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies needed for Selenium and Chrome
# Had to add wget and unzip to get chromedriver
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Download and install Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application code into the container
COPY . .

# Command to run the application using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]
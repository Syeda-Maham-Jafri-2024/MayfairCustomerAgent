#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Variables
IMAGE_NAME="mayfair-voicebot"
IMAGE_TAG="latest"
ACR_NAME="conrainerregistry"
ACR_LOGIN_SERVER="conrainerregistry.azurecr.io"
ACR_USERNAME="conrainerregistry"
ACR_PASSWORD="ixD/dQfxtOvRnWd51IQx1dyE2BANRuq5rf2Oj4dN3t+ACRA9Bd22"

# Functions
error_exit() {
    echo "Error: $1"
    exit 1
}

# Check if Docker is installed
command -v docker >/dev/null 2>&1 || error_exit "Docker is not installed. Please install Docker and try again."

# Validate required variables
if [[ -z "$IMAGE_NAME" || -z "$IMAGE_TAG" || -z "$ACR_NAME" || -z "$ACR_USERNAME" || -z "$ACR_PASSWORD" ]]; then
    error_exit "One or more required variables are not set. Please check the script and set all required variables."
fi

# Build the Docker image
echo "Building Docker image..."
docker build  --no-cache -t "$IMAGE_NAME:$IMAGE_TAG" .
if [[ $? -ne 0 ]]; then
    error_exit "Docker build failed."
fi

# Tag the Docker image
echo "Tagging Docker image..."
docker tag "$IMAGE_NAME:$IMAGE_TAG" "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG"
if [[ $? -ne 0 ]]; then
    error_exit "Docker tag failed."
fi

# Log in to Azure Container Registry
echo "Logging in to Azure Container Registry..."
echo "$ACR_PASSWORD" | docker login "$ACR_LOGIN_SERVER" -u "$ACR_USERNAME" --password-stdin
if [[ $? -ne 0 ]]; then
    error_exit "Docker login failed."
fi

# Push the Docker image to Azure Container Registry
echo "Pushing Docker image to Azure Container Registry..."
docker push "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG"
if [[ $? -ne 0 ]]; then
    error_exit "Docker push failed."
fi

# Log out from Azure Container Registry
echo "Logging out from Azure Container Registry..."
docker logout "$ACR_LOGIN_SERVER"
if [[ $? -ne 0 ]]; then
    error_exit "Docker logout failed."
fi

echo "Docker image pushed successfully!"
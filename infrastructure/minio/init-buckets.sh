#!/bin/sh
set -e

mc alias set myminio http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing myminio/alpr-images
mc mb --ignore-existing myminio/nagare-uploads
mc mb --ignore-existing myminio/reports

mc anonymous set download myminio/alpr-images
echo "MinIO buckets initialised."
